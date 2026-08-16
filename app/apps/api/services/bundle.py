from __future__ import annotations

import sys
from pathlib import Path

PACKAGES = Path(__file__).resolve().parents[3] / "packages"
if str(PACKAGES) not in sys.path:
    sys.path.insert(0, str(PACKAGES))

from domain.config import ConfigBundle, load_bundle  # noqa: E402

from ..models import Session  # noqa: E402
from ..settings import Settings  # noqa: E402


def bundle_from_settings(s: Settings) -> ConfigBundle:
    return load_bundle(
        registry_version=s.registry_version,
        profile_version=s.profile_version,
        thresholds_version=s.thresholds_version,
        norms_version=s.norms_version,
        protocol_version=s.protocol_version,
        rules_version=s.rules_version,
    )


def bundle_from_session(session: Session) -> ConfigBundle:
    """Версии сессии — копии значений на момент обследования (§4 инвариант 3)."""
    return load_bundle(
        registry_version=session.registry_version,
        profile_version=session.profile_version,
        thresholds_version=session.thresholds_version,
        norms_version=session.norms_version,
        protocol_version=session.protocol_version,
        rules_version=session.rules_version,
    )


def bundle_from_versions(v: dict[str, str], protocol_version: str) -> ConfigBundle:
    return load_bundle(
        registry_version=v["registry_version"],
        profile_version=v["profile_version"],
        thresholds_version=v["thresholds_version"],
        norms_version=v["norms_version"],
        protocol_version=protocol_version,
        rules_version=v.get("rules_version", "none"),
    )
