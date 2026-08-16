import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "packages", ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import pytest
from domain.config import load_bundle


@pytest.fixture(scope="session")
def bundle():
    """Текущий набор конфигурации. Версия реестра совпадает с той, на которой
    работает приложение: тесты должны ловить расхождения, а не обходить их."""
    return load_bundle(
        registry_version="2026.3", profile_version="2026.3",
        thresholds_version="demo", norms_version="empty",
        protocol_version="2026.1",
    )


@pytest.fixture(scope="session")
def bundle_2026_1():
    """Предыдущая версия реестра — для проверок совместимости и §12."""
    return load_bundle(
        registry_version="2026.1", profile_version="2026.1",
        thresholds_version="demo", norms_version="empty",
        protocol_version="2026.1",
    )
