"""Исследовательский контур и аналитика (§9.8а ТЗ; Р-14…Р-20, Р-26, Р-35)."""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID

from contracts.schemas import (
    CohortAnalysisOut,
    CohortCreate,
    CohortOut,
    HypothesisCreate,
    HypothesisOut,
    PassportOut,
    ProtocolAnalyticsOut,
    RepeatabilityOut,
)
from domain.hashing import canonical_json, input_hash
from domain.reliability import detectable_effect, operator_variance_share, passport
from domain.stats import (
    benjamini_hochberg,
    multivariate_permutation,
    one_sample_permutation,
    response_axes,
)
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import (
    Analysis,
    Cohort,
    CohortAnalysis,
    Exclusion,
    Hypothesis,
    ParamValue,
    ProtocolDeviation,
    Session,
    Trial,
)
from ..security import Principal, audit, current_principal, require
from ..services.bundle import bundle_from_settings
from ..settings import Settings, get_settings

router = APIRouter(prefix="/research", tags=["research"])

EXPLORATORY_DISCLAIMER = (
    "ПОИСКОВЫЙ АНАЛИЗ. Результат является гипотезой и требует подтверждения "
    "на отложенной части когорты. Выводить из него заключение нельзя."
)


# ── Слой 1. Метрология: собственный SDC (Этап 1.5, Р-20, Р-35) ───────────────

@router.get("/repeatability", response_model=RepeatabilityOut)
async def repeatability(
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require("methodologist", "clinician", "admin")),
    s: Settings = Depends(get_settings),
) -> RepeatabilityOut:
    """Режим повторяемости: test-retest → ICC, SEM, SDC (§9.8а слой 1).

    Внешнего источника SDC для этой комбинации оборудования не существует,
    поэтому платформа ПОРОЖДАЕТ пороги, а не только принимает их.
    Пары строятся по повторным нейтралям внутри сессии одного пациента.
    """
    bundle = bundle_from_settings(s)
    rows = (await db.execute(
        select(ParamValue.param_code, ParamValue.session_id, ParamValue.value,
               ParamValue.trial_id, ParamValue.probe_code)
        .order_by(ParamValue.param_code, ParamValue.session_id)
    )).all()

    grouped: dict[str, dict[str, list[float]]] = {}
    for code, session_id, value, _trial, probe in rows:
        spec = bundle.probes.get(probe)
        if spec is None or not spec.is_neutral:
            continue                       # повторяемость считается по нейтралям
        grouped.setdefault(code, {}).setdefault(str(session_id), []).append(float(value))

    passports: list[PassportOut] = []
    for code, by_subject in sorted(grouped.items()):
        series = [v for v in by_subject.values() if len(v) >= 2]
        if len(series) < 2:
            continue
        p = passport(code, series)
        spec = bundle.registry.get(code)
        passports.append(PassportOut(
            code=code, label_ru=spec.label_ru if spec else code,
            n_subjects=p.n_subjects, n_measurements=p.n_measurements,
            icc=None if p.icc is None else round(p.icc, 4),
            icc_ci=None if p.icc_ci_low is None else [round(p.icc_ci_low, 4),
                                                      round(p.icc_ci_high or 0.0, 4)],
            sem=None if p.sem is None else round(p.sem, 4),
            sdc=None if p.sdc is None else round(p.sdc, 4),
            cv_pct=None if p.cv_pct is None else round(p.cv_pct, 2),
            reliability=p.reliability_label,
            detectable_at_n30=None if p.sdc is None else detectable_effect(p.sdc, 30),
        ))

    operators = (await db.execute(select(Session.operator_ref, Session.id))).all()
    op_map: dict[str, list[float]] = {}
    if passports:
        target = passports[0].code
        for op, session_id in operators:
            vals = [float(v) for c, sid, v, _t, _p in rows if c == target and sid == session_id]
            if vals:
                op_map.setdefault(op, []).extend(vals)

    warning = None
    if not passports:
        warning = (
            "Данных для расчёта недостаточно: нужно ≥2 пациентов с ≥2 повторными "
            "нейтралями. До выпуска собственного SDC суждения о значимости "
            "недействительны (Этап 1.5)."
        )
    await audit(db, principal, "research.repeatability", "cohort", None,
                payload={"params": len(passports)})
    return RepeatabilityOut(
        passports=passports,
        operator_variance_share=operator_variance_share(op_map),
        warning=warning,
    )


# ── Слой 2. Аналитика протокола (Этап 2, Р-35) ───────────────────────────────

@router.get("/protocol-analytics", response_model=ProtocolAnalyticsOut)
async def protocol_analytics(
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require("methodologist", "clinician", "admin")),
    s: Settings = Depends(get_settings),
) -> ProtocolAnalyticsOut:
    """Платформа изучает собственный метод.

    settle_sec и carryover_min в реестре проб — НАЗНАЧЕННЫЕ числа и непроверенные
    допущения. Здесь они калибруются по собственным данным: величина отклика как
    функция фактической выдержки и времени с предыдущей группы.
    """
    bundle = bundle_from_settings(s)
    trials = (await db.execute(select(Trial))).scalars().all()
    analyses = (await db.execute(select(Analysis))).scalars().all()

    response_by_trial: dict[tuple[UUID, str, int], float] = {}
    for a in analyses:
        for r in (a.result or {}).get("responses", []):
            if r.get("delta_index") is not None:
                response_by_trial[(a.session_id, r["probe_code"], r.get("pass_no", 1))] = abs(
                    float(r["delta_index"])
                )

    settle_buckets: dict[str, list[tuple[int, float]]] = {}
    carry_buckets: dict[str, list[tuple[float, float]]] = {}
    for t in trials:
        magnitude = response_by_trial.get((t.session_id, t.probe_code, t.pass_no))
        if magnitude is None:
            continue
        settle_buckets.setdefault(t.probe_code, []).append((t.settle_sec_actual, magnitude))
        if t.minutes_since_prev_group is not None:
            carry_buckets.setdefault(t.probe_code, []).append(
                (float(t.minutes_since_prev_group), magnitude)
            )

    def summarize(points: list[tuple[float, float]], assigned: float, unit: str) -> dict:
        below = [m for x, m in points if x < assigned]
        at_or_above = [m for x, m in points if x >= assigned]
        return {
            "n": len(points),
            "assigned": assigned,
            "unit": unit,
            "mean_below": round(sum(below) / len(below), 4) if below else None,
            "mean_at_or_above": round(sum(at_or_above) / len(at_or_above),
                4) if at_or_above else None,
            "note": "если средние сопоставимы, назначенное значение избыточно",
        }

    settle_calibration = []
    for code, pts in sorted(settle_buckets.items()):
        spec = bundle.probes.get(code)
        if spec and len(pts) >= 3:
            settle_calibration.append(
                {"probe_code": code,
                    **summarize([(float(a), b) for a, b in pts], spec.settle_sec, "sec")}
            )
    carryover_calibration = []
    for code, pts in sorted(carry_buckets.items()):
        spec = bundle.probes.get(code)
        if spec and len(pts) >= 3:
            carryover_calibration.append(
                {"probe_code": code, **summarize(pts, spec.carryover_min, "min")}
            )

    # Урожайность протокола: доля проб, давших интерпретируемый результат.
    threshold = bundle.thresholds.sdc("PI") or 1.0
    yield_rows: dict[str, dict[str, int]] = {}
    for a in analyses:
        for r in (a.result or {}).get("responses", []):
            row = yield_rows.setdefault(r["probe_code"], {"total": 0, "interpretable": 0})
            row["total"] += 1
            d = r.get("delta_index")
            if d is not None and abs(float(d)) >= threshold:
                row["interpretable"] += 1
    yield_by_probe = [
        {"probe_code": code, **v,
         "yield_pct": round(100 * v["interpretable"] / v["total"], 1) if v["total"] else 0.0,
         "note": "низкая урожайность — кандидат на исключение из протокола"}
        for code, v in sorted(yield_rows.items())
    ]

    dev_rows = (await db.execute(
        select(ProtocolDeviation.kind,
            func.count(ProtocolDeviation.id)).group_by(ProtocolDeviation.kind)
    )).all()
    total_sessions = (await db.execute(select(func.count(Session.id)))).scalar_one()
    low_conf = (await db.execute(
        select(func.count(Session.id)).where(Session.low_confidence.is_(True))
    )).scalar_one()

    return ProtocolAnalyticsOut(
        settle_calibration=settle_calibration,
        carryover_calibration=carryover_calibration,
        yield_by_probe=yield_by_probe,
        deviation_summary=[{"kind": k, "count": int(c)} for k, c in dev_rows],
        low_confidence_share=round(low_conf / total_sessions, 4) if total_sessions else None,
    )


# ── Когорты и предрегистрация (§6–§7 исследовательского контура) ─────────────

@router.post("/cohorts", response_model=CohortOut, status_code=status.HTTP_201_CREATED)
async def create_cohort(
    payload: CohortCreate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require("methodologist", "admin")),
) -> CohortOut:
    """Когорта — НЕИЗМЕНЯЕМЫЙ список сессий с датой фиксации. Анализ ссылается
    на когорту, а не на «все данные на момент запуска»."""
    ids = [str(i) for i in payload.session_ids]
    sessions = (await db.execute(
        select(Session).where(Session.id.in_(payload.session_ids))
    )).scalars().all()
    # MUST (Р-24, Р-26): сессия без согласия на участие в исследовании в когорту
    # не входит. Проверка на фиксации когорты, а не при публикации.
    without = [str(s.id) for s in sessions if not s.research_consent_ref]
    if without:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            {"detail": "сессии без согласия на участие в исследовании не включаются в когорту",
             "sessions": without},
        )

    split = int(len(ids) * payload.lockbox_share)
    lockbox = sorted(ids)[:split]
    working = [i for i in ids if i not in lockbox]

    cohort = Cohort(
        name=payload.name, criteria=payload.criteria,
        session_ids=working, lockbox_session_ids=lockbox,
        frozen_at=datetime.now(UTC),
    )
    db.add(cohort)
    await db.flush()
    await audit(db, principal, "cohort.freeze", "cohort", str(cohort.id),
                payload={"working": len(working), "lockbox": len(lockbox)})
    return CohortOut(
        id=cohort.id, name=cohort.name, session_ids=working,  # type: ignore[arg-type]
        lockbox_session_ids=lockbox, frozen_at=cohort.frozen_at,  # type: ignore[arg-type]
        lockbox_opened_at=None,
    )


@router.post("/hypotheses", response_model=HypothesisOut, status_code=status.HTTP_201_CREATED)
async def register_hypothesis(
    payload: HypothesisCreate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require("methodologist", "clinician", "admin")),
    s: Settings = Depends(get_settings),
) -> HypothesisOut:
    """Предрегистрация. Запись неизменяема и хэшируется: молчаливое изменение
    плана становится технически видимым, а не вопросом дисциплины."""
    plan_hash = hashlib.sha256(
        canonical_json({
            "statement": payload.statement, "params": sorted(payload.params),
            "probes": sorted(payload.probe_codes), "plan": payload.analysis_plan,
            "criteria": payload.cohort_criteria, "target_n": payload.target_n,
            "mode": payload.mode, "direction": payload.expected_direction,
        }).encode()
    ).hexdigest()

    # Калькулятор мощности на собственном SDC (§9.8а слой 4): без него target_n
    # заполняется наугад и предрегистрация превращается в формальность.
    bundle = bundle_from_settings(s)
    notes: list[str] = []
    for code in payload.params:
        sdc = bundle.thresholds.sdc(code)
        if sdc:
            eff = detectable_effect(sdc, payload.target_n)
            if eff is not None:
                notes.append(f"{code}: при n={payload.target_n} детектируем сдвиг от {eff} ед.")
    if bundle.thresholds.is_demo:
        notes.append("SDC некалиброван (demo) — расчёт мощности ориентировочный.")

    h = Hypothesis(
        statement=payload.statement, params=payload.params, probe_codes=payload.probe_codes,
        expected_direction=payload.expected_direction, analysis_plan=payload.analysis_plan,
        cohort_criteria=payload.cohort_criteria, target_n=payload.target_n, mode=payload.mode,
        registered_by=principal.actor_ref, plan_hash=plan_hash, status="registered",
    )
    db.add(h)
    await db.flush()
    await audit(db, principal, "hypothesis.register", "hypothesis", str(h.id),
                payload={"mode": payload.mode, "plan_hash": plan_hash})
    return HypothesisOut(
        id=h.id, statement=h.statement, mode=h.mode, status=h.status,  # type: ignore[arg-type]
        target_n=h.target_n, plan_hash=h.plan_hash, registered_at=h.registered_at,
        registered_by=h.registered_by, power_note=" ".join(notes) or None,
    )


@router.get("/hypotheses", response_model=list[HypothesisOut])
async def list_hypotheses(
    db: AsyncSession = Depends(get_db), principal: Principal = Depends(current_principal),
) -> list[HypothesisOut]:
    rows = (
        await db.execute(
            select(Hypothesis).order_by(Hypothesis.registered_at.desc()))).scalars().all()
    return [
        HypothesisOut(
            id=h.id, statement=h.statement, mode=h.mode, status=h.status,  # type: ignore[arg-type]
            target_n=h.target_n, plan_hash=h.plan_hash, registered_at=h.registered_at,
            registered_by=h.registered_by,
        ) for h in rows
    ]


@router.post("/cohorts/{cohort_id}/analyze", response_model=CohortAnalysisOut)
async def analyze_cohort(
    cohort_id: UUID, mode: str = "exploratory", hypothesis_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require("methodologist", "admin")),
    s: Settings = Depends(get_settings),
) -> CohortAnalysisOut:
    """Слой 3 аналитики. Многомерный тест — рядом с одномерными, не вместо.

    Выигрыш: агрегация слабых согласованных сдвигов и одна проверка вместо p.
    Когда эффект присутствует во многих параметрах, но каждый по отдельности
    лежит у порога, поправка на множественность гасит все — а совместный тест
    отвергает нулевую гипотезу (Р-35).
    """
    cohort = await db.get(Cohort, cohort_id)
    if cohort is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "когорта не найдена")

    if mode == "confirmatory":
        if hypothesis_id is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "подтверждающий анализ требует зарегистрированной гипотезы (§6)",
            )
        h = await db.get(Hypothesis, hypothesis_id)
        if h is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "гипотеза не найдена")
        if cohort.lockbox_opened_at is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "lockbox уже открыт: повторный подтверждающий анализ на тех же "
                "отложенных данных невозможен (§7)",
            )
        if h.registered_at > cohort.frozen_at:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "гипотеза зарегистрирована ПОСЛЕ фиксации когорты — подтверждающий "
                "анализ на этих данных недопустим (§6)",
            )
        cohort.lockbox_opened_at = datetime.now(UTC)
        target_sessions = [UUID(i) for i in cohort.lockbox_session_ids]
    else:
        target_sessions = [UUID(i) for i in cohort.session_ids]

    bundle = bundle_from_settings(s)
    analyses = (await db.execute(
        select(Analysis).where(Analysis.session_id.in_(target_sessions))
    )).scalars().all()

    vectors: list[dict[str, float]] = []
    for a in analyses:
        for r in (a.result or {}).get("responses", []):
            vec = {p["code"]: float(p["delta"]) for p in r.get("params", [])}
            if vec:
                vectors.append(vec)

    sdc = {c: v for c in {k for vec in vectors for k in vec}
           if (v := bundle.thresholds.sdc(c)) is not None}

    univariate = {
        code: one_sample_permutation([v[code] for v in vectors if code in v], 2000, 17)
        for code in sorted(sdc)
    }
    fdr = benjamini_hochberg(univariate)
    stat, p_mv = multivariate_permutation(vectors, sdc, 3000, 23)
    axes = response_axes(vectors, sdc)

    exclusions = (await db.execute(
        select(Exclusion.id).where(Exclusion.session_id.in_(target_sessions),
                                   Exclusion.reverted_at.is_(None))
    )).scalars().all()
    excl_hash = hashlib.sha256(
        json.dumps(sorted(str(e) for e in exclusions)).encode()
    ).hexdigest()

    result = {
        "n_vectors": len(vectors),
        "univariate": [
            {"code": r.code, "p": round(r.p_value, 5), "q": r.q_value, "significant": r.significant}
            for r in fdr
        ],
        "multivariate": {
            "statistic": stat, "p": round(p_mv, 5),
            "note": "агрегирует слабые согласованные сдвиги и платит за одну проверку "
                    "вместо p: когда эффект есть во многих параметрах, но каждый у порога, "
                    "поправка на множественность гасит все, а совместный тест — нет",
        },
        "response_axes": [
            {"index": a.index, "explained_share": a.explained_share,
             "top_loadings": dict(sorted(a.loadings.items(), key=lambda kv: -abs(kv[1]))[:5])}
            for a in axes
        ],
    }

    record = CohortAnalysis(
        cohort_id=cohort.id, hypothesis_id=hypothesis_id, mode=mode,
        comparisons_tested=len(univariate), exclusion_set_hash=excl_hash,
        input_hash=input_hash({"sessions": sorted(str(s_) for s_ in target_sessions),
                               "exclusions": excl_hash, "mode": mode}, bundle.versions),
        result=result, **bundle.versions,
    )
    db.add(record)
    await db.flush()
    await audit(db, principal, f"cohort.analyze.{mode}", "cohort_analysis", str(record.id),
                payload={"cohort": str(cohort.id), "comparisons": len(univariate),
                         "sessions": [str(x) for x in target_sessions]})
    return CohortAnalysisOut(
        id=record.id, cohort_id=cohort.id, hypothesis_id=hypothesis_id, mode=mode,  # type: ignore[arg-type]
        comparisons_tested=record.comparisons_tested, input_hash=record.input_hash,
        created_at=record.created_at, result=result,
        disclaimer=EXPLORATORY_DISCLAIMER if mode == "exploratory"
        else "Подтверждающий анализ на отложенной части когорты.",
    )


@router.get("/progress")
async def research_progress(
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(current_principal),
    s: Settings = Depends(get_settings),
) -> dict:
    """Слой 4: метрика накопления знания (§9.8а).

    Сколько параметров вышло из direction=unknown — прямой показатель прогресса
    исследования, а не активности.
    """
    bundle = bundle_from_settings(s)
    total = len(bundle.registry.params)
    known = sum(1 for p in bundle.registry.params.values() if p.direction_known)
    hyp = (await db.execute(select(Hypothesis.status, func.count(Hypothesis.id))
                            .group_by(Hypothesis.status))).all()
    sessions = (await db.execute(select(func.count(Session.id)))).scalar_one()
    return {
        "params_total": total,
        "params_direction_known": known,
        "params_unknown": total - known,
        "direction_known_pct": round(100 * known / total, 1) if total else 0.0,
        "hypotheses": {k: int(v) for k, v in hyp},
        "sessions": int(sessions),
        "note": "Направление меняется с unknown только через подтверждающий анализ (Р-18)",
    }
