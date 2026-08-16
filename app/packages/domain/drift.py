"""Опора нейтрали и дрейф (§8.2 ТЗ; Р-30).

MUST (Р-30): дрейф считается в пространстве параметров, нормированный на SDC —
не через PI (требует норм, которых может не быть) и не через RI (определён
относительно baseline_ref, получается круг).

baseline_ref — среднее нейтралей с ЛИНЕЙНОЙ поправкой на позицию во времени,
то есть значение, предсказанное линейной подгонкой на момент конкретной пробы.
low_confidence выставляется по ОСТАТКУ после поправки: иначе сессия штрафуется
за величину, которую сама же скомпенсировала.
"""
from __future__ import annotations

from dataclasses import dataclass

from .config import ConfigBundle


@dataclass(frozen=True, slots=True)
class NeutralObservation:
    """Одна запись нейтрали. t — секунды от начала сессии (не системные часы)."""

    t: float
    values: dict[str, float]


@dataclass(frozen=True, slots=True)
class BaselineModel:
    """Линейная модель нейтрали по каждому параметру: value ≈ a·t + b."""

    coefficients: dict[str, tuple[float, float]]
    residual_max: dict[str, float]
    n: int

    def at(self, t: float) -> dict[str, float]:
        return {code: a * t + b for code, (a, b) in self.coefficients.items()}


def _fit_line(points: list[tuple[float, float]]) -> tuple[float, float, list[float]]:
    """Метод наименьших квадратов. При n<2 или нулевой дисперсии t — горизонталь."""
    n = len(points)
    mean_y = sum(y for _, y in points) / n
    if n < 2:
        return 0.0, mean_y, [0.0]
    mean_t = sum(t for t, _ in points) / n
    sxx = sum((t - mean_t) ** 2 for t, _ in points)
    if sxx == 0:
        return 0.0, mean_y, [y - mean_y for _, y in points]
    sxy = sum((t - mean_t) * (y - mean_y) for t, y in points)
    a = sxy / sxx
    b = mean_y - a * mean_t
    return a, b, [y - (a * t + b) for t, y in points]


def fit_baseline(neutrals: list[NeutralObservation]) -> BaselineModel:
    if not neutrals:
        raise ValueError("нужна хотя бы одна запись нейтрали")
    ordered = sorted(neutrals, key=lambda o: o.t)
    codes = sorted({c for o in ordered for c in o.values})
    coefficients: dict[str, tuple[float, float]] = {}
    residual_max: dict[str, float] = {}
    for code in codes:
        pts = [(o.t, o.values[code]) for o in ordered if code in o.values]
        if not pts:
            continue
        a, b, residuals = _fit_line(pts)
        coefficients[code] = (a, b)
        residual_max[code] = max((abs(r) for r in residuals), default=0.0)
    return BaselineModel(coefficients=coefficients, residual_max=residual_max, n=len(ordered))


@dataclass(frozen=True, slots=True)
class DriftResult:
    raw_drift: float | None
    residual_drift: float | None
    low_confidence: bool
    worst_param: str | None
    computable: bool
    reason: str | None = None


def baseline_drift(
    neutrals: list[NeutralObservation], model: BaselineModel, bundle: ConfigBundle
) -> DriftResult:
    """drift = max_p |v_last − v_first| / SDC_p; флаг — по остатку после поправки."""
    if len(neutrals) < 2:
        return DriftResult(None, None, False, None, False, "нужно минимум две нейтрали")
    ordered = sorted(neutrals, key=lambda o: o.t)
    first, last = ordered[0], ordered[-1]
    threshold = bundle.thresholds.sdc("drift")
    if threshold is None:
        return DriftResult(None, None, False, None, False, "порог drift не задан")

    raw_worst = 0.0
    residual_worst = 0.0
    worst_param: str | None = None
    any_sdc = False
    for code in sorted(set(first.values) & set(last.values)):
        sdc = bundle.thresholds.sdc(code)
        if sdc is None:
            continue
        any_sdc = True
        raw = abs(last.values[code] - first.values[code]) / sdc
        residual = model.residual_max.get(code, 0.0) / sdc
        if raw > raw_worst:
            raw_worst, worst_param = raw, code
        residual_worst = max(residual_worst, residual)

    if not any_sdc:
        # До Этапа 1.5 собственного SDC нет — контроль честно не работает,
        # а не выдаёт ложное «всё в порядке» (Р-30, Р-32).
        return DriftResult(None, None, False, None, False, "SDC не откалиброван")

    return DriftResult(
        raw_drift=round(raw_worst, 4),
        residual_drift=round(residual_worst, 4),
        low_confidence=residual_worst > threshold,
        worst_param=worst_param,
        computable=True,
    )
