"""Окружение Alembic: схема на Postgres создаётся только миграциями.

Почему URL не в alembic.ini: пароль в файле репозитория недопустим, а два
источника правды (ini и переменная окружения) молча разошлись бы — миграции
пошли бы в одну базу, приложение в другую.

Собственные типы моделей (`GUID`, `JSONB_`) рендерятся в миграции как есть:
подставлять вместо них `sa.JSON()` значило бы записать в схему не тот тип,
который приложение ожидает на Postgres.
"""
from __future__ import annotations

import asyncio
import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT / "packages", ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from apps.api.models import Base                                  # noqa: E402

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

url = os.environ.get("DIERS_DATABASE_URL")
if not url:
    raise RuntimeError(
        "DIERS_DATABASE_URL не задан: миграции не гадают, куда применяться."
    )
config.set_main_option("sqlalchemy.url", url)

target_metadata = Base.metadata


def render_item(type_: str, obj, autogen_context) -> str | bool:
    """Собственные типы печатаются своим именем, а не подменяются базовым."""
    if type_ == "type" and obj.__class__.__module__.endswith("models"):
        autogen_context.imports.add("from apps.api import models")
        return f"models.{obj.__class__.__name__}()"
    return False


def run_migrations_offline() -> None:
    context.configure(
        url=url, target_metadata=target_metadata, literal_binds=True,
        dialect_opts={"paramstyle": "named"}, render_item=render_item,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _run(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata,
                      render_item=render_item, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.", poolclass=pool.NullPool,
    )
    async with engine.connect() as connection:
        await connection.run_sync(_run)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
