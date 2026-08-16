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


@router.get("/{session_id}/compare")
async def compare_probes(
    session_id: UUID, probes: str = "", db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(current_principal),
) -> dict:
    """Обзор «от сустава до стоп» (§14.3) для произвольного набора проб.

    Одна таблица: строки — параметры, сгруппированные по областям тела сверху
    вниз; столбцы — выбранные пробы. Все модальности рядом, а не по отдельным
    экранам: разнести их значило бы сделать сопоставление ручной работой врача.

    MUST §14.2 п. 2: шкала единая по всей панели. §14.2 п. 8: структурные
    величины (ось ног, сила) выводятся без Δ.
    """
    from domain.config import load_anatomy
    from domain.effects import param_effect

    session = await load_session(db, session_id)
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "сессия не найдена")
    bundle = bundle_from_session(session)
    anatomy = load_anatomy()

    by_probe: dict[str, dict[str, float]] = {}
    baseline: dict[str, float] = {}
    for trial in sorted(session.trials, key=lambda t: (t.pass_no, t.ordinal)):
        values: dict[str, float] = {}
        for m in trial.measurements:
            if not m.excluded:
                values.update({k: float(v) for k, v in (m.params or {}).items()})
        if not values:
            continue
        spec = bundle.probes.get(trial.probe_code)
        if spec and spec.is_neutral and trial.pass_no == 1:
            baseline.update(values)
        by_probe.setdefault(trial.probe_code, {}).update(values)

    wanted = [c for c in (probes.split(",") if probes else []) if c in by_probe]
    if not wanted:
        wanted = [c for c in by_probe if not (bundle.probes.get(c) and bundle.probes.get(c).is_neutral)][:3]

    columns = []
    for code in wanted:
        spec = bundle.probes.get(code)
        columns.append({"code": code, "label_ru": spec.label_ru if spec else code,
                        "modality": spec.modality if spec else "unknown"})

    regions = []
    for region in anatomy.ordered():
        rows = []
        codes = {c for probe in wanted for c in by_probe[probe]
                 if (r := anatomy.region_of(c)) and r.key == region.key}
        for code in sorted(codes):
            spec = bundle.registry.get(code)
            cells: dict[str, dict] = {}
            for probe in wanted:
                value = by_probe[probe].get(code)
                if value is None:
                    continue
                base = baseline.get(code)
                if base is None or region.structural:
                    # §14.2 п. 8: структурная величина выводится без Δ,
                    # и без нейтрали отсчитывать тоже не от чего.
                    cells[probe] = {"value": round(value, 3), "delta": None,
                                    "effect_size": None, "confidence": "undefined",
                                    "interpretation": None}
                    continue
                e = param_effect(code, base, value, bundle)
                cells[probe] = {"value": round(value, 3), "delta": e.delta,
                                "effect_size": e.effect_size, "confidence": e.confidence,
                                "interpretation": e.interpretation}
            if cells:
                rows.append({
                    "code": code,
                    "label_ru": spec.label_ru if spec else code,
                    "unit": spec.unit if spec else "",
                    "modality": spec.modality if spec else "unknown",
                    "direction": spec.direction if spec else "unknown",
                    "baseline": None if baseline.get(code) is None else round(baseline[code], 3),
                    "sdc": bundle.thresholds.sdc(code),
                    "cells": cells,
                })
        if rows:
            regions.append({
                "key": region.key, "label_ru": region.label_ru, "hint": region.hint,
                "order": region.order, "structural": region.structural, "rows": rows,
            })

    return {
        "session_id": str(session.id),
        "columns": columns,
        "regions": regions,
        "has_baseline": bool(baseline),
        "note": "Порядок областей задан §14.3 и воспроизводит логику осмотра, "
                "а не удобство вёрстки.",
    }
