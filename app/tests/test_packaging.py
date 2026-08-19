"""Развёртываемость: объявлено ли то, чем код пользуется, и сходится ли схема.

Оба дефекта, ради которых написан этот файл, прошли мимо 153 тестов и упали бы
только в проде: `pypdf` и `pillow` были нужны боевому разбору протоколов и не
значились ни в pyproject, ни в образе, а схема на Postgres не создавалась вовсе.
Тесты, проверяющие поведение, такого класса ошибок не видят: локальное окружение
и sqlite их прячут.
"""
from __future__ import annotations

import ast
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: Модули стандартной библиотеки и собственные пакеты объявления не требуют.
LOCAL = {"domain", "importers", "contracts", "config", "apps", "packages", "tools", "tests"}


def _third_party_imports(root: Path) -> dict[str, set[str]]:
    """Верхнеуровневые имена сторонних модулей → где встретились."""
    found: dict[str, set[str]] = {}
    for path in root.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                # Относительные импорты — свои по определению.
                names = [] if node.level else [(node.module or "").split(".")[0]]
            else:
                continue
            for name in names:
                if not name or name in LOCAL or name in sys.stdlib_module_names:
                    continue
                found.setdefault(name, set()).add(str(path.relative_to(ROOT)))
    return found


#: Имя пакета на PyPI не всегда совпадает с именем модуля.
DISTRIBUTION = {"PIL": "pillow", "yaml": "pyyaml", "sqlalchemy": "sqlalchemy",
                "multipart": "python-multipart", "dotenv": "python-dotenv",
                "pydantic_settings": "pydantic-settings"}


def test_declared_dependencies() -> None:
    """Каждый сторонний импорт боевого кода объявлен в pyproject.

    Именно этого не хватало, чтобы заметить: разбор печатного протокола DIERS
    в контейнере падал бы на ImportError, потому что pypdf в образ не ставился.
    """
    meta = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    declared = {
        req.split(">")[0].split("=")[0].split("[")[0].strip().lower()
        for req in meta["project"]["dependencies"]
    }

    missing: dict[str, set[str]] = {}
    for module, where in _third_party_imports(ROOT / "packages").items():
        dist = DISTRIBUTION.get(module, module).lower().replace("_", "-")
        if dist not in declared:
            missing[dist] = where
    assert not missing, (
        "не объявлены в pyproject.dependencies, но используются боевым кодом: "
        + "; ".join(f"{k} ({', '.join(sorted(v))})" for k, v in sorted(missing.items()))
    )


def test_dockerfile_installs_from_pyproject() -> None:
    """Список зависимостей в образе не дублируется, а берётся из pyproject.

    Два списка уже расходились: boto3 значился только в pyproject. Дубль
    обязательно разойдётся снова — вопрос лишь в том, заметят ли это до прода.
    """
    docker = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "pip install --no-cache-dir ." in docker
    assert "fastapi>=" not in docker, "версии пакетов снова продублированы в Dockerfile"


def test_migrations_match_models(tmp_path) -> None:
    """Схема после миграций совпадает с моделями.

    Расхождение миграций и моделей — тихий дефект: приложение поднимается,
    а падает на первом запросе к недостающему столбцу. Проверяется тем же
    механизмом, что и автогенерация: после `upgrade head` разница должна быть
    пуста.

    Тест синхронный намеренно: env.py запускает миграции через `asyncio.run`,
    а внутри уже работающего цикла это невозможно.
    """
    from alembic import command
    from alembic.autogenerate import compare_metadata
    from alembic.config import Config
    from alembic.migration import MigrationContext
    from sqlalchemy import create_engine

    db = tmp_path / "schema.db"
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "db" / "migrations"))
    import os
    os.environ["DIERS_DATABASE_URL"] = f"sqlite+aiosqlite:///{db}"
    command.upgrade(cfg, "head")

    from apps.api.models import Base
    engine = create_engine(f"sqlite:///{db}")
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    engine.dispose()

    # Индексы, добавленные сырым SQL только для Postgres, на sqlite отсутствуют
    # законно — сравниваются таблицы и столбцы.
    hard = [d for d in diff if not (isinstance(d, tuple) and "index" in str(d[0]))]
    assert not hard, f"схема разошлась с моделями: {hard}"
