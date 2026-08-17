from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from contracts.schemas import (
    AnalysisOut, AnalyzeIn, ConfigVersions, ReportCreate, ReportOut, SignIn,
)
from domain.protocol import ProtocolError, assert_transition

from ..db import get_db
from ..models import Analysis, Report, Session
from ..security import Principal, assert_report_allowed, audit, current_principal, require
from ..services.bundle import bundle_from_session, bundle_from_versions
from ..services.session_service import load_session, run_analysis
from ..settings import Settings, get_settings

router = APIRouter(tags=["analyses"])


@router.post("/sessions/{session_id}/analyze", response_model=AnalysisOut)
async def analyze_session(
    session_id: UUID, payload: AnalyzeIn | None = None,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require("clinician", "methodologist", "admin")),
) -> AnalysisOut:
    session = await load_session(db, session_id)
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "сессия не найдена")

    bundle = (
        bundle_from_versions(payload.versions.model_dump(), session.protocol_version)
        if payload and payload.versions else bundle_from_session(session)
    )
    try:
        result = run_analysis(session, bundle)
    except ValueError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e

    # Р-34: тот же вход и те же версии дают тот же input_hash — повторный анализ
    # не создаёт строки. Именно это делает автопереанализ дешёвым: рост
    # «сессии × версии» не наступает.
    existing = (await db.execute(
        select(Analysis).where(
            Analysis.session_id == session.id, Analysis.input_hash == result.input_hash
        )
    )).scalar_one_or_none()
    if existing is not None:
        return _analysis_out(existing)

    # Проверка выше не атомарна: два одновременных запроса на анализ (два окна,
    # повтор после таймаута, автопереанализ рядом с ручным) оба увидят «записи
    # нет» и оба попробуют вставить. Уникальность (session_id, input_hash) в этот
    # момент отрабатывает как задумано, но необработанная IntegrityError выходит
    # наружу пятисоткой — притом что произошло ровно то, чего мы и добивались:
    # анализ с этим входом уже сохранён. Гонка здесь — штатное течение событий,
    # а не сбой, и отвечать на неё надо сохранённой записью.
    record = Analysis(
        session_id=session.id, input_hash=result.input_hash, index_kind=result.index_kind,
        result=result.to_dict(), **result.versions,
    )
    try:
        async with db.begin_nested():
            db.add(record)
            await db.flush()
    except IntegrityError:
        existing = (await db.execute(
            select(Analysis).where(
                Analysis.session_id == session.id, Analysis.input_hash == result.input_hash
            )
        )).scalar_one_or_none()
        if existing is None:
            # Значит нарушено не то ограничение — молчать нельзя.
            raise
        return _analysis_out(existing)

    session.low_confidence = result.low_confidence
    if session.status == "shortlist_confirmed":
        session.status = "analyzed"
    await db.flush()
    await audit(db, principal, "session.analyzed", "analysis", str(record.id),
                payload={"input_hash": result.input_hash, "index": result.index_kind})
    return _analysis_out(record)


def _analysis_out(a: Analysis) -> AnalysisOut:
    return AnalysisOut(
        id=a.id, session_id=a.session_id, input_hash=a.input_hash,
        versions=ConfigVersions(
            norms_version=a.norms_version, thresholds_version=a.thresholds_version,
            rules_version=a.rules_version, profile_version=a.profile_version,
            registry_version=a.registry_version,
        ),
        index_kind=a.index_kind, created_at=a.created_at, result=a.result,  # type: ignore[arg-type]
    )


@router.get("/analyses/{analysis_id}", response_model=AnalysisOut)
async def get_analysis(
    analysis_id: UUID, db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(current_principal),
) -> AnalysisOut:
    a = await db.get(Analysis, analysis_id)
    if a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "анализ не найден")
    return _analysis_out(a)


@router.post("/analyses/{analysis_id}/report", response_model=ReportOut,
             status_code=status.HTTP_201_CREATED)
async def create_report(
    analysis_id: UUID, payload: ReportCreate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require("clinician", "methodologist", "admin")),
    s: Settings = Depends(get_settings),
) -> ReportOut:
    a = await db.get(Analysis, analysis_id)
    if a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "анализ не найден")
    assert_report_allowed(principal, payload.variant, s)

    document = {
        "analysis": str(a.id), "variant": payload.variant, "versions": {
            "norms": a.norms_version, "thresholds": a.thresholds_version,
            "rules": a.rules_version, "profile": a.profile_version, "registry": a.registry_version,
        },
        "intended_use": s.intended_use,          # MUST §1: печатается в каждом отчёте
        "index_kind": a.index_kind,
        "result": a.result,
    }
    doc_hash = hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()

    report = Report(analysis_id=a.id, variant=payload.variant, status="draft", document_hash=doc_hash)
    db.add(report)

    session = await db.get(Session, a.session_id)
    if session is not None and session.status == "analyzed":
        # Р-33: статус выставляется при выпуске ПЕРВОГО отчёта; последующие
        # варианты состояние не меняют и ошибкой не являются.
        session.status = "reported"
    await db.flush()
    await audit(db, principal, "report.create", "report", str(report.id),
                payload={"variant": payload.variant, "document_hash": doc_hash})
    return _report_out(report)


def _report_out(r: Report) -> ReportOut:
    return ReportOut(
        id=r.id, analysis_id=r.analysis_id, variant=r.variant,  # type: ignore[arg-type]
        status=r.status, document_hash=r.document_hash,  # type: ignore[arg-type]
        signed_by=r.signed_by, signed_at=r.signed_at,
        watermark=r.status != "signed",
    )


@router.post("/analyses/{analysis_id}/sign", response_model=ReportOut)
async def sign_report(
    analysis_id: UUID, report_id: UUID, payload: SignIn,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require("clinician")),
) -> ReportOut:
    """MUST (Р-22): подписывается ХЭШ СФОРМИРОВАННОГО ДОКУМЕНТА, а не запись в БД.

    ФЗ-63 «Об электронной подписи»; Приказ МЗ РФ № 947н. Нажатие кнопки
    медицинским документом отчёт не делает. Метка доверенного времени обязательна:
    без неё истечение срока сертификата обесценивает подпись задним числом.
    """
    report = await db.get(Report, report_id)
    if report is None or report.analysis_id != analysis_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "отчёт не найден")
    if report.status == "signed":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "документ уже подписан и неизменяем: исправление выпускается новым "
            "документом со ссылкой на исправляемый (Р-22)",
        )
    if payload.signed_document_hash != report.document_hash:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "подписан не тот документ: хэш не совпадает с выпущенным",
        )
    if not payload.timestamp_token:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "требуется метка доверенного времени: без неё истечение срока "
            "сертификата обесценит подпись задним числом (Р-22)",
        )

    report.signature = payload.signature
    report.timestamp_token = payload.timestamp_token
    report.signed_by = payload.clinician_ref
    report.signed_at = datetime.now(timezone.utc)
    report.status = "signed"
    await db.flush()
    await audit(db, principal, "report.sign", "report", str(report.id),
                payload={"clinician": payload.clinician_ref, "document_hash": report.document_hash})
    return _report_out(report)


@router.get("/patients/{patient_ref}/history")
async def history(
    patient_ref: str, db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(current_principal),
) -> dict:
    """§12 + Р-2: сверка сопоставимости идёт по analyses, а не по sessions.

    По умолчанию берётся самый свежий набор версий, доступный ДЛЯ ВСЕХ сессий —
    это превращает §12 из ограничения в рабочее правило: история остаётся связной,
    пока для сессий существует общий пересчёт.
    """
    sessions = (await db.execute(
        select(Session).where(Session.patient_ref == patient_ref).order_by(Session.started_at)
    )).scalars().all()
    if not sessions:
        return {"visits": [], "comparable": False, "reason": "нет сессий"}

    analyses = (await db.execute(
        select(Analysis).where(Analysis.session_id.in_([s.id for s in sessions]))
        .order_by(Analysis.created_at.desc())
    )).scalars().all()

    by_session: dict[UUID, list[Analysis]] = {}
    for a in analyses:
        by_session.setdefault(a.session_id, []).append(a)

    def key(a: Analysis) -> tuple[str, ...]:
        # rules_version в проверку НЕ входит (Р-3): правила влияют на рекомендации,
        # а не на измеренные величины.
        return (a.norms_version, a.thresholds_version, a.profile_version, a.registry_version)

    common: set[tuple[str, ...]] | None = None
    for s in sessions:
        keys = {key(a) for a in by_session.get(s.id, [])}
        common = keys if common is None else (common & keys)
    common = common or set()

    neutral_defs = {s.neutral_definition for s in sessions}
    if len(neutral_defs) > 1:
        return {
            "visits": [{"session_id": str(s.id), "started_at": s.started_at.isoformat(),
                        "neutral_definition": s.neutral_definition} for s in sessions],
            "comparable": False,
            "reason": "neutral_definition различается между визитами — разности не вычисляются (§12)",
        }
    if not common:
        return {
            "visits": [{"session_id": str(s.id), "started_at": s.started_at.isoformat()}
                       for s in sessions],
            "comparable": False,
            "reason": "нет общего набора версий конфигурации; требуется переанализ (Р-2)",
        }

    chosen = sorted(common)[-1]
    visits = []
    for s in sessions:
        match = next((a for a in by_session.get(s.id, []) if key(a) == chosen), None)
        if match is None:
            continue
        res = match.result or {}
        visits.append({
            "session_id": str(s.id),
            "started_at": s.started_at.isoformat(),
            "index_kind": match.index_kind,
            "low_confidence": s.low_confidence,
            "shortlist": res.get("shortlist", []),
            "best_response": min(
                (r.get("delta_index") for r in res.get("responses", [])
                 if r.get("delta_index") is not None), default=None,
            ),
        })
    return {
        "visits": visits,
        "comparable": True,
        "versions": dict(zip(
            ("norms_version", "thresholds_version", "profile_version", "registry_version"), chosen
        )),
        "note": "Набор версий выбран как самый свежий, общий для всех визитов (Р-2)",
    }
