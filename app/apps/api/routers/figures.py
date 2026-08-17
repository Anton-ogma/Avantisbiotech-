"""Иллюстрации приборных протоколов (Р-40).

Отдаются вместе с метаданными и данными в `data:`-URI. Причина не в удобстве
фронтенда: контур замкнут (Р-23), внешних CDN нет, а отдельный запрос за каждой
картинкой на экране сравнения проб — это десятки round-trip на одну сессию.
Иллюстрации протокола малы (десятки килобайт), их дешевле отдать сразу.

Порог `MAX_INLINE_TOTAL` не даёт этому решению испортиться при росте: если
иллюстраций окажется много, ответ обрежется явно и скажет об этом, а не
распухнет молча.
"""
from __future__ import annotations

import base64
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import ImportFigure, RawImport, Trial
from ..security import Principal, current_principal
from ..services.bundle import bundle_from_session
from ..services.session_service import load_session

router = APIRouter(tags=["figures"])

#: Суммарный предел на инлайн в одном ответе. Выше — только ссылки на /figures/{id}.
MAX_INLINE_TOTAL = 4 * 1024 * 1024


@router.get("/sessions/{session_id}/figures")
async def session_figures(
    session_id: UUID, db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(current_principal),
) -> dict:
    session = await load_session(db, session_id)
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "сессия не найдена")
    bundle = bundle_from_session(session)

    rows = (await db.execute(
        select(ImportFigure, Trial, RawImport)
        .join(RawImport, ImportFigure.raw_import_id == RawImport.id)
        .outerjoin(Trial, ImportFigure.trial_id == Trial.id)
        .where(RawImport.session_id == session_id)
        .order_by(ImportFigure.created_at, ImportFigure.ordinal)
    )).all()

    out: list[dict] = []
    budget = MAX_INLINE_TOTAL
    truncated = 0
    for figure, trial, raw in rows:
        probe_code = trial.probe_code if trial is not None else None
        spec = bundle.probes.get(probe_code) if probe_code else None
        item = {
            "id": str(figure.id),
            "probe_code": probe_code,
            "probe_label_ru": spec.label_ru if spec else probe_code,
            "format_id": raw.format_id,
            "name": figure.name,
            "kind": figure.kind,
            "mime": figure.mime,
            "width": figure.width,
            "height": figure.height,
            "structures": list(figure.structures or []),
            "page": figure.page,
            "data_uri": None,
            "url": f"/figures/{figure.id}",
        }
        if len(figure.data) <= budget:
            budget -= len(figure.data)
            item["data_uri"] = (
                f"data:{figure.mime};base64,"
                + base64.b64encode(figure.data).decode("ascii")
            )
        else:
            truncated += 1
        out.append(item)

    return {
        "session_id": str(session.id),
        "figures": out,
        "truncated": truncated,
        "structures": sorted({s for f in out for s in f["structures"]}),
        "note": (
            "Иллюстрации протокола прибора. Значения, напечатанные на них "
            "растром, в текстовый слой не попадают и парсером не читаются: "
            "подписи здесь — изображение, а не данные (флаг импорта "
            "figure_values_not_in_text_layer)."
        ),
    }


@router.get("/figures/{figure_id}")
async def figure_content(
    figure_id: UUID, db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(current_principal),
) -> Response:
    figure = await db.get(ImportFigure, figure_id)
    if figure is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "иллюстрация не найдена")
    return Response(
        content=figure.data, media_type=figure.mime,
        # Иллюстрация неизменна: она — часть импортированного файла, а импорт
        # идемпотентен по хешу (§4 инвариант 1). Кэшировать можно навсегда.
        headers={"Cache-Control": "private, max-age=31536000, immutable"},
    )
