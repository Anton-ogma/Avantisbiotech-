"""Роли, доступ, аудит (§15 ТЗ; Р-24, Р-33).

Аутентификация вынесена за модуль: хост передаёт заверенный контекст.
ПДн внутрь не попадают — только patient_ref, роль и идентификатор актора (Р-9).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Literal

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .models import AuditLog
from .settings import Settings, get_settings

Role = Literal["operator", "clinician", "methodologist", "coach", "admin"]

#: Матрица «роль → допустимые варианты отчёта» (Р-33). До неё patient и dentist
#: были вариантами без ролей, methodologist и operator — ролями без вариантов.
REPORT_MATRIX: dict[str, frozenset[str]] = {
    "clinician": frozenset({"doctor", "dentist", "patient", "coach"}),
    "methodologist": frozenset({"doctor", "dentist"}),      # обезличенные
    "coach": frozenset({"coach"}),                          # только свой, при согласии
    "operator": frozenset(),
    "admin": frozenset(),
}

#: MUST (Р-33): в режиме research эти варианты не выпускаются вовсе — оба содержат
#: предписания, а research терапевтических выводов не даёт (Р-19, Р-25).
RESEARCH_FORBIDDEN_VARIANTS = frozenset({"patient", "coach"})


@dataclass(frozen=True, slots=True)
class Principal:
    actor_ref: str
    role: Role


async def current_principal(
    x_actor_ref: str = Header(..., alias="X-Actor-Ref"),
    x_actor_role: str = Header(..., alias="X-Actor-Role"),
) -> Principal:
    if x_actor_role not in REPORT_MATRIX:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"неизвестная роль: {x_actor_role}")
    return Principal(actor_ref=x_actor_ref, role=x_actor_role)  # type: ignore[arg-type]


def require(*roles: Role):
    async def _dep(principal: Principal = Depends(current_principal)) -> Principal:
        if principal.role not in roles:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"роль {principal.role} не имеет доступа; требуется одна из {', '.join(roles)}",
            )
        return principal
    return _dep


def assert_report_allowed(principal: Principal, variant: str, settings: Settings) -> None:
    if settings.intended_use == "research" and variant in RESEARCH_FORBIDDEN_VARIANTS:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"вариант «{variant}» содержит предписания и в режиме research не выпускается "
            "(Р-33): платформа не является медицинским изделием и терапевтических "
            "выводов не даёт",
        )
    if variant not in REPORT_MATRIX.get(principal.role, frozenset()):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"роль {principal.role} не может получать вариант «{variant}» (Р-33)",
        )


def _hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            default=str).encode()
    ).hexdigest()


async def audit(
    db: AsyncSession,
    principal: Principal,
    action: str,
    entity: str,
    entity_id: str | None = None,
    *,
    payload: dict[str, Any] | None = None,
    before: Any = None,
    after: Any = None,
) -> None:
    """MUST (Р-21): для экспорта фиксируется СОСТАВ выгрузки, а не только факт.
    ФЗ-152 ст. 21 — 24 часа на уведомление; без состава круг субъектов не определить.
    """
    db.add(AuditLog(
        actor=principal.actor_ref,
        role=principal.role,
        action=action,
        entity=entity,
        entity_id=entity_id,
        before_hash=None if before is None else _hash(before),
        after_hash=None if after is None else _hash(after),
        payload=payload or {},
    ))
    await db.flush()


async def audit_dep(db: AsyncSession = Depends(get_db)) -> AsyncSession:
    return db


def settings_dep() -> Settings:
    return get_settings()
