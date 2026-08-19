"""Фоновые задачи (§3 ТЗ: Redis + ARQ).

Здесь живёт всё, что не должно происходить в HTTP-запросе: разбор больших файлов,
материализация витрины, автопереанализ при публикации конфигурации (Р-34).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT / "packages", ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from typing import ClassVar

from sqlalchemy import select

from apps.api.db import sessionmaker
from apps.api.models import Analysis, Session
from apps.api.services.bundle import bundle_from_versions
from apps.api.services.session_service import load_session, run_analysis
from apps.api.settings import get_settings


async def reanalyze_all(ctx, versions: dict[str, str]) -> dict:
    """Р-34: публикация новой версии конфигурации ставит переанализ ВСЕХ сессий.

    Без этого история §12 деградирует при каждом изменении реестра параметров,
    а изменения будут частыми (Р-18). Дублей не создаёт: UNIQUE (session_id,
    input_hash) отбрасывает вставку, когда результат не изменился.
    """
    created = skipped = failed = 0
    async with sessionmaker()() as db:
        ids = (await db.execute(select(Session.id))).scalars().all()
        for session_id in ids:
            session = await load_session(db, session_id)
            if session is None:
                continue
            try:
                bundle = bundle_from_versions(versions, session.protocol_version)
                result = run_analysis(session, bundle)
            except ValueError:
                failed += 1
                continue
            exists = (await db.execute(
                select(Analysis.id).where(
                    Analysis.session_id == session_id, Analysis.input_hash == result.input_hash
                )
            )).scalar_one_or_none()
            if exists:
                skipped += 1
                continue
            db.add(Analysis(
                session_id=session_id, input_hash=result.input_hash,
                index_kind=result.index_kind, result=result.to_dict(), **result.versions,
            ))
            created += 1
        await db.commit()
    return {"created": created, "skipped": skipped, "failed": failed}


class WorkerSettings:
    functions: ClassVar[list] = [reanalyze_all]
    max_jobs = 8
    job_timeout = 900

    @staticmethod
    def redis_settings():
        from arq.connections import RedisSettings
        return RedisSettings.from_dsn(get_settings().redis_url)
