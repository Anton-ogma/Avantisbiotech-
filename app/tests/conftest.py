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
    return load_bundle(
        registry_version="2026.1", profile_version="2026.1",
        thresholds_version="demo", norms_version="empty",
        protocol_version="2026.1",
    )
