"""Сборка входа домена из БД и запуск анализа.

Граница: здесь весь I/O, в packages/domain — ни одного (§3 ТЗ).
"""
from __future__ import annotations

from uuid import UUID

from domain.analysis import AnalysisResult, SessionInput, TrialInput, analyze, interim_plan
from domain.config import ConfigBundle
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..models import Session, Trial


async def load_session(db: AsyncSession, session_id: UUID) -> Session | None:
    stmt = (
        select(Session)
        .where(Session.id == session_id)
        .options(selectinload(Session.trials).selectinload(Trial.measurements),
                 selectinload(Session.plan))
    )
    return (await db.execute(stmt)).scalar_one_or_none()


def to_domain(session: Session, bundle: ConfigBundle) -> SessionInput:
    trials: list[TrialInput] = []
    for trial in sorted(session.trials, key=lambda t: (t.pass_no, t.t_offset_sec)):
        values: dict[str, float] = {}
        flags: list[str] = []
        excluded = False
        for m in trial.measurements:
            if m.excluded:
                excluded = True
                continue
            values.update({k: float(v) for k, v in (m.params or {}).items()})
            flags.extend(m.quality_flags or [])
        spec = bundle.probes.get(trial.probe_code)
        trials.append(TrialInput(
            trial_id=str(trial.id),
            probe_code=trial.probe_code,
            role=trial.role,
            pass_no=trial.pass_no,
            t=float(trial.t_offset_sec),
            is_neutral=bool(spec.is_neutral) if spec else trial.is_baseline,
            values=values,
            quality_flags=flags,
            excluded=excluded or not values,
        ))
    return SessionInput(
        session_id=str(session.id),
        patient_ref=session.patient_ref,
        neutral_definition=session.neutral_definition,
        study_mode=session.study_mode,
        trials=trials,
    )


def run_analysis(session: Session, bundle: ConfigBundle) -> AnalysisResult:
    return analyze(to_domain(session, bundle), bundle)


def run_interim(session: Session, bundle: ConfigBundle, top: int = 2) -> list[str]:
    return interim_plan(to_domain(session, bundle), bundle, top)


async def materialize_param_values(db: AsyncSession, session: Session) -> int:
    """Витрина для когортных запросов. JSONB хорош для хранения, но «все пациенты
    со значением выше X» по нему читается плохо — на миллионе пациентов это
    разница между индексным сканом и полным перебором."""
    from ..models import ParamValue

    await db.execute(
        ParamValue.__table__.delete().where(ParamValue.session_id == session.id)
    )
    count = 0
    for trial in session.trials:
        for m in trial.measurements:
            if m.excluded:
                continue
            for code, value in (m.params or {}).items():
                db.add(ParamValue(
                    session_id=session.id, trial_id=trial.id, probe_code=trial.probe_code,
                    pass_no=trial.pass_no, param_code=code, value=float(value),
                    observed_at=session.started_at,
                ))
                count += 1
    await db.flush()
    return count
