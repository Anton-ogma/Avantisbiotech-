"""Сводка по пробе через три модальности и классификация (§9.5)."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from domain.crossmodal import ProbeSynthesis, rank_probes, synthesize_probe

from ..db import get_db
from ..security import Principal, current_principal
from ..services.bundle import bundle_from_session
from ..services.session_service import load_session

router = APIRouter(prefix="/sessions", tags=["crossmodal"])


def _signal(s) -> dict:
    return {"available": s.available, "delta": s.delta, "reliable": s.reliable, "detail": s.detail}


def _out(p: ProbeSynthesis) -> dict:
    return {
        "probe_code": p.probe_code, "label_ru": p.label_ru,
        "posture": _signal(p.posture), "joint": _signal(p.joint), "muscle": _signal(p.muscle),
        "coherence": p.coherence, "verdict": p.verdict, "verdict_ru": p.verdict_ru,
        "rationale": p.rationale,
        "excursion": None if p.excursion is None else {
            "status": p.excursion.status, "delta_mm": p.excursion.delta_mm,
            "message": p.excursion.message,
        },
        "params": [{
            "code": e.code, "label_ru": e.label_ru if hasattr(e, "label_ru") else e.code,
            "delta": e.delta, "effect_size": e.effect_size, "confidence": e.confidence,
            "direction": e.direction, "interpretation": e.interpretation,
        } for e in p.posture.params],
    }


@router.get("/{session_id}/crossmodal")
async def crossmodal(
    session_id: UUID, db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(current_principal),
) -> dict:
    session = await load_session(db, session_id)
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "сессия не найдена")
    bundle = bundle_from_session(session)

    by_probe: dict[str, dict[str, float]] = {}
    modalities: dict[str, set[str]] = {}
    baseline: dict[str, float] = {}
    for trial in sorted(session.trials, key=lambda t: (t.pass_no, t.ordinal)):
        values: dict[str, float] = {}
        for m in trial.measurements:
            if m.excluded:
                continue
            values.update({k: float(v) for k, v in (m.params or {}).items()})
            modalities.setdefault(trial.probe_code, set()).add(m.modality)
        if not values:
            continue
        spec = bundle.probes.get(trial.probe_code)
        if spec and spec.is_neutral and trial.pass_no == 1:
            baseline.update(values)
        by_probe.setdefault(trial.probe_code, {}).update(values)

    if not baseline:
        return {"session_id": str(session.id), "probes": [], "ranking": {},
                "warning": "в сессии нет нейтрали — отклики считать не от чего (§8)"}

    def is_probe(code: str) -> bool:
        spec = bundle.probes.get(code)
        if spec is None:
            return True
        # Нейтраль — опора, а не отклик. Myoline — сессионное измерение и в анализе
        # проб не участвует (§9.8 MUST), в ранжирование его пускать нельзя.
        return not spec.is_neutral and spec.modality != "myoline"

    syntheses = [
        synthesize_probe(code, values, baseline, bundle)
        for code, values in by_probe.items() if is_probe(code)
    ]
    ranking = rank_probes(syntheses)

    session_level = {
        code: values for code, values in by_probe.items()
        if (spec := bundle.probes.get(code)) and spec.modality == "myoline"
    }

    return {
        "session_id": str(session.id),
        "modalities": {k: sorted(v) for k, v in sorted(modalities.items())},
        "session_level": {
            "myoline": next(iter(session_level.values()), {}),
            "note": "изометрическая сила — ковариата дозирования, в анализе проб "
                    "не участвует (§9.8 MUST)",
        },
        "probes": [_out(p) for p in syntheses],
        "ranking": {k: [p.probe_code for p in v] for k, v in ranking.items()},
        "note": (
            "Классификация описывает измеренный отклик, а не назначение: "
            "в режиме research движок правил выключен, переход от «даёт наибольшее "
            "улучшение позы» к «назначить» делает врач (Р-19)."
        ),
    }
