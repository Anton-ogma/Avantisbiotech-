"""Метрология: ICC, SEM, SDC (§9.8а, слой 1; Р-20, Р-35).

Платформа порождает собственные пороги: внешнего источника для этой комбинации
оборудования не существует. Здесь считается то, что становится
thresholds/sdc_<version>.yaml с source: own_repeatability.

ICC(2,1) — двусторонняя случайная модель, абсолютное согласие: субъекты и
измерения случайны, важна именно согласованность значений, а не только их
корреляция.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ParamPassport:
    """Паспорт параметра — он же закрывает требование `source` в §10."""

    code: str
    n_subjects: int
    n_measurements: int
    mean: float
    sd: float
    icc: float | None
    icc_ci_low: float | None
    icc_ci_high: float | None
    sem: float | None
    sdc: float | None
    cv_pct: float | None
    reliability_label: str

    def as_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "n_subjects": self.n_subjects,
            "n_measurements": self.n_measurements,
            "mean": round(self.mean, 4),
            "sd": round(self.sd, 4),
            "icc": None if self.icc is None else round(self.icc, 4),
            "icc_ci": None
            if self.icc_ci_low is None
            else [round(self.icc_ci_low, 4), round(self.icc_ci_high or 0.0, 4)],
            "sem": None if self.sem is None else round(self.sem, 4),
            "sdc": None if self.sdc is None else round(self.sdc, 4),
            "cv_pct": None if self.cv_pct is None else round(self.cv_pct, 2),
            "reliability": self.reliability_label,
        }


def _label(icc: float | None) -> str:
    if icc is None:
        return "не определена"
    if icc < 0.5:
        return "низкая"
    if icc < 0.75:
        return "средняя"
    if icc < 0.9:
        return "хорошая"
    return "отличная"


def icc_2_1(rows: list[list[float]]) -> tuple[float | None, float | None, float | None]:
    """ICC(2,1). rows[i] — повторные измерения одного субъекта (k на субъекта).

    Возвращает (ICC, нижняя граница 95%, верхняя граница 95%). Границы —
    нормальная аппроксимация по преобразованию Фишера; при малом n это грубо,
    но честнее, чем печатать точечную оценку без интервала.
    """
    rows = [r for r in rows if len(r) >= 2]
    n = len(rows)
    if n < 2:
        return None, None, None
    k = min(len(r) for r in rows)
    rows = [r[:k] for r in rows]

    grand = sum(sum(r) for r in rows) / (n * k)
    row_means = [sum(r) / k for r in rows]
    col_means = [sum(rows[i][j] for i in range(n)) / n for j in range(k)]

    ms_r = k * sum((m - grand) ** 2 for m in row_means) / (n - 1)
    ms_c = n * sum((m - grand) ** 2 for m in col_means) / (k - 1) if k > 1 else 0.0
    ss_e = sum(
        (rows[i][j] - row_means[i] - col_means[j] + grand) ** 2 for i in range(n) for j in range(k)
    )
    df_e = (n - 1) * (k - 1)
    ms_e = ss_e / df_e if df_e > 0 else 0.0

    denom = ms_r + (k - 1) * ms_e + k * (ms_c - ms_e) / n
    if denom <= 0:
        return None, None, None
    icc = (ms_r - ms_e) / denom
    icc = max(-1.0, min(1.0, icc))

    if abs(icc) >= 0.999 or n < 4:
        return icc, None, None
    zf = 0.5 * math.log((1 + icc) / (1 - icc))
    se = 1 / math.sqrt(max(n - 3, 1))
    lo, hi = (math.tanh(zf - 1.96 * se), math.tanh(zf + 1.96 * se))
    return icc, lo, hi


def passport(code: str, rows: list[list[float]]) -> ParamPassport:
    """SEM = SD·√(1−ICC); SDC = 1,96·√2·SEM (§9.8а)."""
    flat = [v for r in rows for v in r]
    n_meas = len(flat)
    if n_meas == 0:
        raise ValueError("нет измерений")
    mean = sum(flat) / n_meas
    var = sum((v - mean) ** 2 for v in flat) / (n_meas - 1) if n_meas > 1 else 0.0
    sd = math.sqrt(var)

    icc, lo, hi = icc_2_1(rows)
    sem = None if icc is None or icc >= 1 else sd * math.sqrt(max(0.0, 1 - icc))
    sdc = None if sem is None else 1.96 * math.sqrt(2) * sem
    cv = None if mean == 0 else abs(sd / mean) * 100

    return ParamPassport(
        code=code,
        n_subjects=len([r for r in rows if len(r) >= 2]),
        n_measurements=n_meas,
        mean=mean,
        sd=sd,
        icc=icc,
        icc_ci_low=lo,
        icc_ci_high=hi,
        sem=sem,
        sdc=sdc,
        cv_pct=cv,
        reliability_label=_label(icc),
    )


def operator_variance_share(by_operator: dict[str, list[float]]) -> float | None:
    """Доля дисперсии, приходящаяся на оператора (§9.8а, слой 1).

    MUST печатать: если она сравнима с эффектом пробы, выводы недостоверны
    независимо от статистики. Это часто крупнейший источник разброса.
    """
    groups = [v for v in by_operator.values() if len(v) >= 2]
    if len(groups) < 2:
        return None
    flat = [v for g in groups for v in g]
    n = len(flat)
    grand = sum(flat) / n
    ss_total = sum((v - grand) ** 2 for v in flat)
    if ss_total == 0:
        return 0.0
    ss_between = sum(len(g) * ((sum(g) / len(g)) - grand) ** 2 for g in groups)
    return round(ss_between / ss_total, 4)


def detectable_effect(sdc: float, n: int) -> float | None:
    """Калькулятор мощности на собственном SDC (§9.8а, слой 4; Р-35).

    Минимальный средний сдвиг, детектируемый при n наблюдениях, мощность 80%,
    двусторонний α=0.05. Без него hypotheses.target_n заполняется наугад,
    и предрегистрация превращается в формальность.
    """
    if n < 2 or sdc <= 0:
        return None
    sd = sdc / (1.96 * math.sqrt(2))          # обратный ход к SEM
    return round((1.96 + 0.84) * sd / math.sqrt(n), 4)
