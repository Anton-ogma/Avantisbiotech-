"""Каталог мышц, шаблоны монтажей и монтаж сессии (Р-42).

Каталог и шаблоны — только чтение: это конфигурация, а не пользовательские
данные. Монтаж сессии пишется оператором и версионируется историей строк:
переназначение канала — событие, о котором спросят при разборе расхождений.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from domain.config import load_montages, load_muscles
from domain.montage import (MontageError, build_montage, from_template,
                            montage_from_channels)

from ..db import get_db
from ..models import MontageTemplateRow, SessionMontageRow
from ..security import Principal, audit, current_principal, require
from ..services.session_service import load_session

router = APIRouter(tags=["montage"])


class ChannelIn(BaseModel):
    label: str = Field(min_length=1, max_length=64,
                       description="как канал подписан на миографе: CH1, MASS_L, «жев слева»")
    muscle: str = Field(min_length=1, max_length=64)
    side: str = Field(pattern="^[LlRr]$")


class MontageIn(BaseModel):
    #: Либо шаблон, либо ручная пропись, либо шаблон + правки.
    template: str | None = None
    channels: list[ChannelIn] = Field(default_factory=list)
    note: str = ""


@router.get("/emg/muscles")
async def muscles(principal: Principal = Depends(current_principal)) -> dict:
    catalog = load_muscles()
    return {
        "version": catalog.version,
        "muscles": [
            {"code": m.code, "label_ru": m.label_ru, "latin": m.latin, "region": m.region,
             "surface": m.surface, "note": m.note, "aliases": list(m.aliases)}
            for m in catalog.muscles
        ],
        "note": (
            "surface=false — мышца в каталоге есть, но поверхностными электродами "
            "не снимается: в монтаж такой канал не допускается."
        ),
    }


@router.get("/emg/montages")
async def montages(
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(current_principal),
) -> dict:
    lib = load_montages()
    catalog = load_muscles()
    out = []
    for m in lib.montages:
        channels = []
        for ch in m.channels:
            muscle = catalog.get(ch.muscle)
            for side in ch.sides():
                channels.append({
                    "label": f"{ch.muscle}_{side}",
                    "muscle": ch.muscle,
                    "muscle_label_ru": muscle.label_ru if muscle else ch.muscle,
                    "side": side,
                })
        out.append({"code": m.code, "label_ru": m.label_ru, "purpose": m.purpose,
                    "channels": channels, "channel_count": len(channels),
                    "builtin": True, "groups": _groups(m.channels, catalog)})

    rows = (await db.execute(
        select(MontageTemplateRow)
        .where(MontageTemplateRow.archived.is_(False))
        .order_by(MontageTemplateRow.created_at)
    )).scalars().all()
    out.extend(_template_out(r) for r in rows)

    return {"version": lib.version, "montages": out,
            "note": ("Шаблон — заготовка: оператор правит метки и состав под свою "
                     "запись. builtin=false — свой шаблон клиники.")}


def _groups(channels, catalog) -> list[dict]:
    """Состав шаблона в виде «мышца + стороны» — то, из чего его собирали."""
    return [{"muscle": ch.muscle, "side": ch.side,
             "muscle_label_ru": (m.label_ru if (m := catalog.get(ch.muscle)) else ch.muscle),
             "region": m.region if m else "unknown"}
            for ch in channels]


def _template_out(row: MontageTemplateRow) -> dict:
    catalog = load_muscles()
    channels = []
    for ch in (row.channels or []):
        muscle = catalog.get(ch["muscle"])
        for side in (("L", "R") if ch.get("side", "both") == "both" else (ch["side"].upper(),)):
            channels.append({
                "label": f"{ch['muscle']}_{side}", "muscle": ch["muscle"],
                "muscle_label_ru": muscle.label_ru if muscle else ch["muscle"], "side": side,
            })
    return {
        "code": row.code, "label_ru": row.label_ru, "purpose": row.purpose,
        "channels": channels, "channel_count": len(channels), "builtin": False,
        "created_by": row.created_by,
        "groups": [
            {"muscle": ch["muscle"], "side": ch.get("side", "both"),
             "muscle_label_ru": (m.label_ru if (m := catalog.get(ch["muscle"])) else ch["muscle"]),
             "region": m.region if m else "unknown"}
            for ch in (row.channels or [])
        ],
    }


class GroupChannelIn(BaseModel):
    muscle: str = Field(min_length=1, max_length=64)
    #: both — два отвода; L или R — односторонний, законен и осознан.
    side: str = Field(default="both", pattern="^(both|[LlRr])$")


class TemplateIn(BaseModel):
    code: str = Field(min_length=2, max_length=64, pattern=r"^[A-Za-z0-9_\-]+$")
    label_ru: str = Field(min_length=1, max_length=128)
    purpose: str = ""
    channels: list[GroupChannelIn] = Field(min_length=1)


@router.post("/emg/montages", status_code=status.HTTP_201_CREATED)
async def create_template(
    payload: TemplateIn, db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require("operator", "clinician", "methodologist", "admin")),
) -> dict:
    """Свой шаблон монтажа: набор мышц под собственный протокол (Р-45).

    Проверяется тем же кодом, что и поставляемые шаблоны: недоступная
    поверхностно мышца и повтор канала отклоняются здесь, а не всплывают
    пустой колонкой через месяц.
    """
    if load_montages().get(payload.code) is not None:
        # Перекрытие поставляемого шаблона запрещено: уже загруженные сессии
        # ссылаются на его код, и подмена состава задним числом объявила бы их
        # записанными не тем.
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"код {payload.code} занят поставляемым шаблоном — выберите другой")
    existing = (await db.execute(
        select(MontageTemplateRow).where(MontageTemplateRow.code == payload.code)
    )).scalar_one_or_none()
    if existing is not None and not existing.archived:
        raise HTTPException(status.HTTP_409_CONFLICT, f"шаблон {payload.code} уже есть")

    try:
        montage = montage_from_channels(
            [c.model_dump() for c in payload.channels],
            code=payload.code, label_ru=payload.label_ru)
    except MontageError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from e

    row = existing or MontageTemplateRow(code=payload.code, created_by=principal.actor_ref)
    row.label_ru, row.purpose, row.archived = payload.label_ru, payload.purpose, False
    row.channels = [c.model_dump() for c in payload.channels]
    if existing is None:
        db.add(row)
    await db.flush()
    await audit(db, principal, "montage_template.saved", "montage_template", row.code,
                payload={"channels": len(montage.channels)})
    return {"template": _template_out(row), "warnings": list(montage.warnings)}


@router.delete("/emg/montages/{code}")
async def archive_template(
    code: str, db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require("operator", "clinician", "methodologist", "admin")),
) -> dict:
    """Шаблон архивируется, а не удаляется: на него ссылаются прошлые сессии."""
    row = (await db.execute(
        select(MontageTemplateRow).where(MontageTemplateRow.code == code)
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"шаблона {code} нет")
    row.archived = True
    await db.flush()
    await audit(db, principal, "montage_template.archived", "montage_template", code)
    return {"code": code, "archived": True,
            "note": "шаблон скрыт из списка; сессии, записанные по нему, не тронуты"}


@router.get("/sessions/{session_id}/montage")
async def get_montage(
    session_id: UUID, db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(current_principal),
) -> dict:
    row = await _current(db, session_id)
    if row is None:
        return {"session_id": str(session_id), "montage": None,
                "note": ("Монтаж не задан. Каналы опознаются только по меткам, "
                         "которые платформа знает; «CH1» останется неопознанным.")}
    return {"session_id": str(session_id), "montage": _out(row)}


@router.put("/sessions/{session_id}/montage")
async def set_montage(
    session_id: UUID, payload: MontageIn,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require("operator", "clinician", "admin")),
) -> dict:
    session = await load_session(db, session_id)
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "сессия не найдена")

    try:
        if payload.channels:
            # Ручная пропись главнее шаблона: оператор видел провода, шаблон нет.
            montage = build_montage(
                [c.model_dump() for c in payload.channels],
                template=payload.template, note=payload.note,
            )
        elif payload.template:
            montage = from_template(payload.template) if load_montages().get(payload.template) \
                else await _from_saved_template(db, payload.template)
        else:
            raise MontageError("нужен либо шаблон, либо список каналов")
    except MontageError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from e

    row = SessionMontageRow(
        session_id=session.id, template=montage.template, note=montage.note,
        channels=[{"label": c.label, "muscle": c.muscle, "side": c.side}
                  for c in montage.channels],
        set_by=principal.actor_ref,
    )
    db.add(row)
    await db.flush()
    await audit(db, principal, "session.montage_set", "session", str(session.id),
                payload={"template": montage.template, "channels": len(montage.channels)})
    return {"session_id": str(session.id), "montage": _out(row),
            "warnings": list(montage.warnings)}


async def _from_saved_template(db: AsyncSession, code: str):
    row = (await db.execute(
        select(MontageTemplateRow).where(MontageTemplateRow.code == code)
    )).scalar_one_or_none()
    if row is None:
        raise MontageError(f"шаблона {code!r} нет ни в библиотеке, ни среди своих")
    return montage_from_channels(list(row.channels or []), code=row.code, label_ru=row.label_ru)


async def _current(db: AsyncSession, session_id: UUID) -> SessionMontageRow | None:
    """Действующий монтаж — последняя строка. История остаётся: канал могли
    переназначить, и «когда именно» — вопрос к журналу, а не к догадкам."""
    return (await db.execute(
        select(SessionMontageRow)
        .where(SessionMontageRow.session_id == session_id)
        .order_by(SessionMontageRow.created_at.desc(), SessionMontageRow.id.desc())
        .limit(1)
    )).scalar_one_or_none()


def _out(row: SessionMontageRow) -> dict:
    catalog = load_muscles()
    return {
        "id": str(row.id), "template": row.template, "note": row.note,
        "set_by": row.set_by, "created_at": row.created_at,
        "channels": [
            {**ch, "muscle_label_ru": (m.label_ru if (m := catalog.get(ch["muscle"])) else ch["muscle"]),
             "param_code": f"EMG_RMS_{ch['muscle']}_{ch['side']}"}
            for ch in (row.channels or [])
        ],
    }
