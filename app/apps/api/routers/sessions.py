from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from contracts.schemas import (
    ConfigVersions,
    InterimOut,
    PlanCreate,
    PlannedProbeIn,
    PlanOut,
    QualityItem,
    QualityReviewIn,
    SessionCreate,
    SessionOut,
    ShortlistIn,
    TrialCreate,
)
from domain.protocol import (
    PlannedProbe,
    ProtocolError,
    TrialFact,
    assert_transition,
    randomize_within_groups,
    reconcile_with_plan,
    validate_plan,
    validate_trial,
)
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import (
    Exclusion,
    Measurement,
    PatientRef,
    ProtocolDeviation,
    Session,
    SessionPlan,
    Trial,
)
from ..security import Principal, audit, current_principal, require
from ..services.bundle import bundle_from_session, bundle_from_settings
from ..services.session_service import load_session, run_interim
from ..settings import Settings, get_settings

router = APIRouter(prefix="/sessions", tags=["sessions"])


def _out(s: Session, trial_count: int = 0) -> SessionOut:
    return SessionOut(
        id=s.id, patient_ref=s.patient_ref, status=s.status, study_mode=s.study_mode,
        neutral_definition=s.neutral_definition, low_confidence=s.low_confidence,
        started_at=s.started_at, operator_ref=s.operator_ref,
        versions=ConfigVersions(
            norms_version=s.norms_version, thresholds_version=s.thresholds_version,
            rules_version=s.rules_version, profile_version=s.profile_version,
            registry_version=s.registry_version,
        ),
        protocol_version=s.protocol_version, trial_count=trial_count, pass_count=s.pass_count,
    )


@router.post("", response_model=SessionOut, status_code=status.HTTP_201_CREATED)
async def create_session(
    payload: SessionCreate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require("operator", "clinician", "admin")),
    s: Settings = Depends(get_settings),
) -> SessionOut:
    # MUST (Р-24, Р-29): ИДС проверяется ПРИ СОЗДАНИИ. Согласие предшествует
    # вмешательству; проверка на неявном переходе фиксировала бы нарушение
    # постфактум, когда обследование уже проведено.
    if not payload.informed_consent_ref.strip():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "нет действующего ИДС (ФЗ-323 ст. 20; Приказ МЗ РФ № 390н)",
        )
    if payload.study_mode and not payload.research_consent_ref:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "исследовательская сессия требует отдельного согласия на участие "
            "в исследовании — ИДС его не заменяет (Р-24)",
        )

    patient = await db.get(PatientRef, payload.patient_ref)
    if patient is None:
        patient = PatientRef(
            patient_ref=payload.patient_ref, neutral_definition=payload.neutral_definition
        )
        db.add(patient)
        await db.flush()
    elif patient.unlinked_at is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "согласие отозвано, соответствие уничтожено: новые сессии под этим "
            "patient_ref невозможны (Р-24)",
        )

    b = bundle_from_settings(s)
    session = Session(
        patient_ref=payload.patient_ref,
        protocol_version=s.protocol_version,
        operator_ref=payload.operator_ref,
        study_mode=payload.study_mode,
        randomization_scheme=payload.randomization_scheme,
        randomization_seed=payload.randomization_seed,
        patient_blinded=payload.patient_blinded,
        operator_blinded=payload.operator_blinded,
        # Копия значения на момент сессии (Р-8), не ссылка на текущее у пациента.
        neutral_definition=payload.neutral_definition,
        lld_mm=payload.lld_mm,
        platform_config_baseline=payload.platform_config_baseline,
        informed_consent_ref=payload.informed_consent_ref,
        research_consent_ref=payload.research_consent_ref,
        status="prepared",
        **b.versions,
    )
    db.add(session)
    await db.flush()
    await audit(db, principal, "session.create", "session", str(session.id),
                payload={"patient_ref": payload.patient_ref, "study_mode": payload.study_mode})
    return _out(session)


@router.get("", response_model=list[SessionOut])
async def list_sessions(
    limit: int = 50, offset: int = 0,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(current_principal),
) -> list[SessionOut]:
    counts = (
        select(Trial.session_id,
            func.count(Trial.id).label("n")).group_by(Trial.session_id).subquery()
    )
    rows = (await db.execute(
        select(Session, func.coalesce(counts.c.n, 0))
        .outerjoin(counts, counts.c.session_id == Session.id)
        .order_by(Session.started_at.desc())
        .limit(min(limit, 200)).offset(offset)
    )).all()
    return [_out(s, int(n)) for s, n in rows]


@router.get("/{session_id}", response_model=SessionOut)
async def get_session(
    session_id: UUID, db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(current_principal),
) -> SessionOut:
    s = await load_session(db, session_id)
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "сессия не найдена")
    return _out(s, len(s.trials))


@router.post("/{session_id}/plan", response_model=PlanOut)
async def approve_plan(
    session_id: UUID, payload: PlanCreate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require("operator", "clinician", "admin")),
) -> PlanOut:
    """Р-29: утверждение плана ДО первой пробы. Здесь проверяются валидаторы
    полноты и порядка — на выходе из probes_running они бесполезны, пациент ушёл."""
    session = await load_session(db, session_id)
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "сессия не найдена")
    try:
        assert_transition(session.status, "plan_approved")  # type: ignore[arg-type]
    except ProtocolError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e

    bundle = bundle_from_session(session)
    planned = [PlannedProbe(p.probe_code, "", p.position, p.pass_no) for p in payload.probes]
    violations = validate_plan(
        planned, bundle,
        study_mode=session.study_mode,
        lld_measured=session.lld_mm is not None,
        randomization_scheme=session.randomization_scheme,
        randomization_seed=session.randomization_seed,
    )
    blocking = [v for v in violations if v.blocking]
    if blocking:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            {"detail": "план не соответствует протоколу",
             "violations": [{"code": v.code, "message": v.message} for v in blocking]},
        )

    if payload.apply_randomization and session.randomization_scheme != "none":
        planned = randomize_within_groups(planned, bundle, session.randomization_seed or 0)

    plan = SessionPlan(
        session_id=session.id,
        probes=[{"probe_code": p.probe_code, "position": p.position, "pass_no": p.pass_no}
                for p in planned],
        randomization={"scheme": session.randomization_scheme, "seed": session.randomization_seed},
        approved_by=principal.actor_ref,
        approved_at=datetime.now(UTC),
    )
    db.add(plan)
    session.status = "plan_approved"
    await db.flush()
    await audit(db, principal, "session.plan_approved", "session", str(session.id),
                payload={"probes": len(plan.probes)}, after=plan.probes)
    return PlanOut(
        session_id=session.id,
        probes=[PlannedProbeIn(**p) for p in plan.probes],
        approved_by=plan.approved_by, approved_at=plan.approved_at, violations=[],
    )


@router.get("/{session_id}/plan", response_model=PlanOut)
async def get_plan(
    session_id: UUID, db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(current_principal),
) -> PlanOut:
    session = await load_session(db, session_id)
    if session is None or session.plan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "план не утверждён")
    devs = (await db.execute(
        select(ProtocolDeviation).where(ProtocolDeviation.session_id == session_id)
    )).scalars().all()
    return PlanOut(
        session_id=session.id,
        probes=[PlannedProbeIn(**p) for p in session.plan.probes],
        approved_by=session.plan.approved_by, approved_at=session.plan.approved_at,
        deviations=[{"kind": d.kind, "probe_code": d.probe_code, "reason": d.reason} for d in devs],
    )


@router.post("/{session_id}/trials", status_code=status.HTTP_201_CREATED)
async def add_trial(
    session_id: UUID, payload: TrialCreate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require("operator", "clinician", "admin")),
) -> dict:
    session = await load_session(db, session_id)
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "сессия не найдена")
    if session.status == "prepared":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "план не утверждён: до утверждения плана не выполняется ни одна проба (Р-29)",
        )
    bundle = bundle_from_session(session)
    spec = bundle.probes.get(payload.probe_code)
    if spec is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"проба {payload.probe_code} отсутствует в реестре")

    violations = validate_trial(TrialFact(
        probe_code=payload.probe_code, position=payload.position, pass_no=payload.pass_no,
        settle_sec_actual=payload.settle_sec_actual,
        minutes_since_prev_group=payload.minutes_since_prev_group,
        excursion_mm=payload.excursion_mm, effort_achieved_pct=payload.effort_achieved_pct,
    ), bundle)
    if violations:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            {"detail": "проба не соответствует протоколу",
             "violations": [{"code": v.code, "message": v.message} for v in violations]},
        )

    trial = Trial(
        session_id=session.id, probe_code=payload.probe_code, ordinal=payload.position,
        pass_no=payload.pass_no, role=payload.role, mode=payload.mode,
        is_baseline=spec.is_neutral, t_offset_sec=payload.t_offset_sec,
        settle_sec_actual=payload.settle_sec_actual,
        minutes_since_prev_group=payload.minutes_since_prev_group,
        excursion_mm=payload.excursion_mm,
        effort={"achieved_pct": payload.effort_achieved_pct} if payload.effort_achieved_pct else {},
        platform_config=payload.platform_config,
    )
    db.add(trial)
    # Неявные переходы по факту появления данных (Р-7, Р-29)
    if spec.is_neutral and session.status == "plan_approved":
        session.status = "baseline_recorded"
    elif not spec.is_neutral and session.status in ("plan_approved", "baseline_recorded"):
        session.status = "probes_running"
    elif session.status == "imported":
        assert_transition("imported", "probes_running")   # цикл, Р-28
        session.status = "probes_running"
    session.pass_count = max(session.pass_count, payload.pass_no)
    await db.flush()
    await audit(db, principal, "trial.create", "trial", str(trial.id),
                payload={"probe": payload.probe_code, "pass": payload.pass_no})
    return {"id": str(trial.id), "session_status": session.status}


@router.post("/{session_id}/interim", response_model=InterimOut)
async def interim(
    session_id: UUID, top: int = 2,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require("operator", "clinician", "admin")),
) -> InterimOut:
    """Р-28: промежуточный расчёт для подтверждающего повтора.

    Отдаёт ТОЛЬКО коды проб. Величины, размеры эффекта и направление скрыты:
    иначе слепота разбора качества (Р-17) снимается до его закрытия — тот, кто
    видит величины откликов, уже знает, какая проба «сработала».
    """
    session = await load_session(db, session_id)
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "сессия не найдена")
    bundle = bundle_from_session(session)
    try:
        codes = run_interim(session, bundle, top)
    except ValueError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    await audit(db, principal, "session.interim", "session", str(session.id),
                payload={"codes": codes})
    return InterimOut(probe_codes=codes)


@router.get("/{session_id}/quality", response_model=list[QualityItem])
async def quality_queue(
    session_id: UUID, db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require("operator", "clinician", "methodologist", "admin")),
) -> list[QualityItem]:
    """MUST (Р-17): экран разбора СЛЕПОЙ. Код пробы, роль, порядковый номер и
    результаты анализа здесь не отдаются — иначе исключение артефактов становится
    необъявленной степенью свободы исследователя."""
    session = await load_session(db, session_id)
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "сессия не найдена")
    items: list[QualityItem] = []
    for trial in session.trials:
        for m in trial.measurements:
            items.append(QualityItem(
                measurement_id=m.id, modality=m.modality,
                quality_flags=list(m.quality_flags or []), param_count=len(m.params or {}),
            ))
    items.sort(key=lambda i: str(i.measurement_id))   # порядок не выдаёт очерёдность проб
    return items


@router.post("/{session_id}/quality-review")
async def quality_review(
    session_id: UUID, payload: QualityReviewIn,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require("clinician", "methodologist", "admin")),
) -> dict:
    session = await load_session(db, session_id)
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "сессия не найдена")
    try:
        assert_transition(session.status, "quality_reviewed")  # type: ignore[arg-type]
    except ProtocolError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e

    excluded = 0
    for d in payload.decisions:
        m = await db.get(Measurement, d.measurement_id)
        if m is None:
            continue
        if d.verdict == "exclude":
            m.excluded = True
            excluded += 1
            # Р-17: исключение ОБРАТИМО. Необратимое равносильно потере данных,
            # поэтому физическое удаление измерений запрещено.
            db.add(Exclusion(
                session_id=session.id, entity="measurement", entity_id=m.id,
                reason_code=d.reason_code, reason_text=d.reason_text,
                decided_by=principal.actor_ref, blinded=True,
            ))
        else:
            m.excluded = False

    # Сверка факта с планом (Р-29): расхождения — данные, а не ошибка.
    if session.plan:
        planned = [PlannedProbe(p["probe_code"], "", p["position"], p.get("pass_no", 1))
                   for p in session.plan.probes]
        facts = [TrialFact(t.probe_code, t.ordinal, t.pass_no, t.settle_sec_actual,
                           t.minutes_since_prev_group, t.excursion_mm, None)
                 for t in session.trials]
        for dev in reconcile_with_plan(planned, facts):
            db.add(ProtocolDeviation(
                session_id=session.id, kind=dev.kind, probe_code=dev.probe_code,
                reason=dev.reason, recorded_by=principal.actor_ref,
            ))

    session.status = "quality_reviewed"
    await db.flush()
    await audit(db, principal, "session.quality_reviewed", "session", str(session.id),
                payload={"decisions": len(payload.decisions), "excluded": excluded})
    return {"status": session.status, "excluded": excluded}


@router.post("/{session_id}/shortlist")
async def confirm_shortlist(
    session_id: UUID, payload: ShortlistIn,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require("clinician", "admin")),
) -> dict:
    session = await load_session(db, session_id)
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "сессия не найдена")
    try:
        assert_transition(session.status, "shortlist_confirmed")  # type: ignore[arg-type]
    except ProtocolError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    session.status = "shortlist_confirmed"
    await db.flush()
    await audit(db, principal, "session.shortlist_confirmed", "session", str(session.id),
                payload={"codes": payload.confirmed_probe_codes})
    return {"status": session.status, "confirmed": payload.confirmed_probe_codes}


@router.get("/{session_id}/measurements")
async def measurements(
    session_id: UUID, db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(current_principal),
) -> dict:
    """Канонические значения по пробам — для модальностей, которые не сводятся
    к отклику от нейтрали (кондилография, динамика). Р-36."""
    session = await load_session(db, session_id)
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "сессия не найдена")
    bundle = bundle_from_session(session)
    out = []
    for trial in sorted(session.trials, key=lambda t: (t.pass_no, t.ordinal)):
        spec = bundle.probes.get(trial.probe_code)
        params = []
        flags: list[str] = []
        for m in trial.measurements:
            flags.extend(m.quality_flags or [])
            for code, value in sorted((m.params or {}).items()):
                p = bundle.registry.get(code)
                params.append({
                    "code": code, "value": value,
                    "label_ru": p.label_ru if p else code,
                    "unit": p.unit if p else "",
                    "domain": p.domain if p else "unknown",
                    "modality": p.modality if p else m.modality,
                    "direction": p.direction if p else "unknown",
                    "in_index": bool(p and p.in_pi),
                })
        out.append({
            "trial_id": str(trial.id), "probe_code": trial.probe_code,
            "label_ru": spec.label_ru if spec else trial.probe_code,
            "modality": spec.modality if spec else "unknown",
            "pass_no": trial.pass_no, "quality_flags": sorted(set(flags)), "params": params,
        })
    return {"session_id": str(session.id), "started_at": session.started_at.isoformat(),
            "device": (session.platform_config_baseline or {}).get("device"), "trials": out}
