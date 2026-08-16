"""Индексы PI и RI (§9.1, §9.2 ТЗ; Р-13).

PI — популяционный, требует норм. RI — отзывчивость, опирается на собственную
нейтраль пациента и норм НЕ требует.

MUST (Р-13): отсутствие норм не блокирует ни один сценарий. Параметр без норм
входит в RI и не входит в PI; колонка нормы для него — прочерк, а не ноль.
"""
from __future__ import annotations

from dataclasses import dataclass

from .config import ConfigBundle, ParamSpec

ZCategory = str  # normal | borderline | deviation | severe | undefined


@dataclass(frozen=True, slots=True)
class ParamZ:
    code: str
    value: float
    z: float | None
    category: ZCategory
    norm_defined: bool


@dataclass(frozen=True, slots=True)
class IndexResult:
    total: float | None
    by_domain: dict[str, float]
    contributing: int
    skipped: int

    @property
    def defined(self) -> bool:
        return self.total is not None


def z_score(value: float, mean: float, sd: float) -> float:
    if sd <= 0:
        raise ValueError("sd должно быть положительным")
    return (value - mean) / sd


def z_category(z: float | None, bundle: ConfigBundle) -> ZCategory:
    if z is None:
        return "undefined"
    cats = bundle.profile.z_categories
    a = float(cats.get("normal", 1.0))
    b = float(cats.get("borderline", 2.0))
    c = float(cats.get("deviation", 3.0))
    az = abs(z)
    if az < a:
        return "normal"
    if az < b:
        return "borderline"
    if az < c:
        return "deviation"
    return "severe"


def compute_z(values: dict[str, float], bundle: ConfigBundle) -> dict[str, ParamZ]:
    out: dict[str, ParamZ] = {}
    for code, value in values.items():
        spec = bundle.registry.get(code)
        if spec is None:
            continue
        norm = bundle.norms.get(code)
        if norm is None:
            out[code] = ParamZ(code, value, None, "undefined", False)
            continue
        z = z_score(value, norm.mean, norm.sd)  # type: ignore[arg-type]
        out[code] = ParamZ(code, value, z, z_category(z, bundle), True)
    return out


def _aggregate(
    contributions: dict[str, tuple[ParamSpec, float]], bundle: ConfigBundle
) -> IndexResult:
    by_domain: dict[str, float] = {}
    for spec, magnitude in contributions.values():
        by_domain[spec.domain] = by_domain.get(spec.domain, 0.0) + spec.weight * magnitude
    total = 0.0
    for domain, raw in by_domain.items():
        total += bundle.profile.domain_weights.get(domain, 0.0) * raw
    return IndexResult(
        total=round(total, 6),
        by_domain={d: round(v, 6) for d, v in sorted(by_domain.items())},
        contributing=len(contributions),
        skipped=0,
    )


def postural_index(values: dict[str, float], bundle: ConfigBundle) -> IndexResult:
    """PI = Σ_domain W_domain · Σ_p w_p · min(|z_p|, z_cap).

    Возвращает total=None, если ни один параметр не имеет норм — это штатно
    и означает «PI не определён», а не «PI равен нулю».
    """
    cap = bundle.profile.z_cap
    contributions: dict[str, tuple[ParamSpec, float]] = {}
    skipped = 0
    for code, value in values.items():
        spec = bundle.registry.get(code)
        if spec is None or not spec.in_pi or spec.weight <= 0:
            continue
        norm = bundle.norms.get(code)
        if norm is None:
            skipped += 1
            continue
        z = z_score(value, norm.mean, norm.sd)  # type: ignore[arg-type]
        contributions[code] = (spec, min(abs(z), cap))
    if not contributions:
        return IndexResult(total=None, by_domain={}, contributing=0, skipped=skipped)
    res = _aggregate(contributions, bundle)
    return IndexResult(res.total, res.by_domain, res.contributing, skipped)


def response_index(deltas: dict[str, float], bundle: ConfigBundle) -> IndexResult:
    """RI = Σ_domain W_domain · Σ_p w_p · min(|Δ_p| / SDC_p, ri_cap).

    Норм не требует. По модулю — поэтому параметр с direction=unknown (Р-18)
    входит наравне с остальными, а знак нигде не интерпретируется.
    """
    cap = bundle.profile.ri_cap
    contributions: dict[str, tuple[ParamSpec, float]] = {}
    skipped = 0
    for code, delta in deltas.items():
        spec = bundle.registry.get(code)
        if spec is None or not spec.in_pi or spec.weight <= 0:
            continue
        sdc = bundle.thresholds.sdc(code)
        if sdc is None:
            skipped += 1
            continue
        contributions[code] = (spec, min(abs(delta) / sdc, cap))
    if not contributions:
        return IndexResult(total=None, by_domain={}, contributing=0, skipped=skipped)
    res = _aggregate(contributions, bundle)
    return IndexResult(res.total, res.by_domain, res.contributing, skipped)
