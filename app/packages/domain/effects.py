"""Эффекты проб (§9.3–§9.7 ТЗ; Р-4, Р-5, Р-6, Р-14, Р-18).

Знаковое соглашение: индексы неотрицательны и означают «удалённость», поэтому
ΔPI/ΔRI < 0 — улучшение. Лучший из двух одиночных = минимальный.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .config import ConfigBundle

Confidence = Literal["noise", "probable", "reliable", "undefined"]
CombinedVerdict = Literal["conflict", "synergistic", "dominant", "additive", "indeterminate"]
Coherence = Literal["full", "partial", "posture_only", "posture_muscle_conflict", "undefined"]


@dataclass(frozen=True, slots=True)
class ParamEffect:
    code: str
    baseline: float
    value: float
    delta: float
    sdc: float | None
    effect_size: float | None
    confidence: Confidence
    direction: str
    #: Клиническая трактовка. None, когда direction=unknown (Р-18) — знак не
    #: интерпретируется, цвет нейтральный, слова «улучшение»/«ухудшение» не звучат.
    interpretation: Literal["improving", "worsening"] | None


def classify(effect_size: float | None) -> Confidence:
    """|effect| < 1 шум, 1..2 вероятный, ≥2 достоверный (§9.3)."""
    if effect_size is None:
        return "undefined"
    a = abs(effect_size)
    if a < 1.0:
        return "noise"
    if a < 2.0:
        return "probable"
    return "reliable"


def param_effect(code: str, baseline: float, value: float, bundle: ConfigBundle) -> ParamEffect:
    spec = bundle.registry.get(code)
    direction = spec.direction if spec else "unknown"
    sdc = bundle.thresholds.sdc(code)
    delta = value - baseline
    effect_size = None if sdc is None else delta / sdc
    confidence = classify(effect_size)

    interpretation: Literal["improving", "worsening"] | None = None
    if confidence in ("probable", "reliable"):
        if direction == "higher_worse":
            interpretation = "improving" if delta < 0 else "worsening"
        elif direction == "lower_worse":
            interpretation = "improving" if delta > 0 else "worsening"
        elif direction == "two_sided":
            # Уход от нормы в любую сторону хуже; без норм судить не о чем.
            norm = bundle.norms.get(code)
            if norm is not None:
                before, after = abs(baseline - norm.mean), abs(value - norm.mean)  # type: ignore[arg-type]
                interpretation = "improving" if after < before else "worsening"
        # direction == "unknown" → остаётся None: предрешать результат нельзя.

    return ParamEffect(
        code=code,
        baseline=round(baseline, 6),
        value=round(value, 6),
        delta=round(delta, 6),
        sdc=sdc,
        effect_size=None if effect_size is None else round(effect_size, 4),
        confidence=confidence,
        direction=direction,
        interpretation=interpretation,
    )


def combined_verdict(
    d_ab: float, d_a: float, d_b: float, threshold: float
) -> CombinedVerdict:
    """§9.7. Порядок проверки НОРМАТИВЕН (Р-4): условия пересекаются, первое выигрывает.

    conflict первым — безопасная сторона: комбинация хуже лучшего одиночного остаётся
    конфликтом, даже если численно совпала с суммой (§11 запрещает назначать оба).
    dominant раньше additive — когда вклад одного в пределах шума, «работает один
    уровень» честнее, чем «вклады сложились»: второе подталкивает назначить оба.
    """
    add = d_a + d_b
    best = min(d_a, d_b)
    if d_ab > best + threshold:
        return "conflict"
    if d_ab < add - threshold:
        return "synergistic"
    if abs(d_ab - best) < threshold:
        return "dominant"
    if abs(d_ab - add) < threshold:
        return "additive"
    return "indeterminate"


def coherence(
    posture_delta: float | None,
    joint_delta: float | None,
    muscle_delta: float | None,
    threshold: float,
) -> Coherence:
    """§9.5. Значение переименовано из conflict в posture_muscle_conflict (Р-6):
    слово занято вердиктом §9.7, а в отчёте оба поля стоят рядом."""
    if posture_delta is None:
        return "undefined"
    posture_reliable = abs(posture_delta) >= threshold
    if not posture_reliable:
        return "undefined"
    posture_improves = posture_delta < 0

    signals = [d for d in (joint_delta, muscle_delta) if d is not None and abs(d) >= threshold]
    if posture_improves and muscle_delta is not None and muscle_delta >= threshold:
        return "posture_muscle_conflict"
    if not signals:
        return "posture_only"
    agreeing = sum(1 for d in signals if (d < 0) == posture_improves)
    if agreeing == 2:
        return "full"
    if agreeing == 1:
        return "partial"
    return "posture_only"


@dataclass(frozen=True, slots=True)
class ProbeResponse:
    probe_code: str
    pass_no: int
    delta_index: float | None
    index_kind: Literal["RI", "PI"]
    confidence: Confidence
    params: list[ParamEffect]
    confirmed: bool = False
    #: False, когда ни один достоверно изменившийся параметр не имеет известного
    #: направления (Р-18). Тогда у отклика есть ВЕЛИЧИНА, но нет знака, и он не
    #: принадлежит ни шорт-листу, ни списку ухудшений: назначать знак нечем.
    direction_known: bool = True

    @property
    def improving(self) -> bool:
        return self.direction_known and self.delta_index is not None and self.delta_index < 0


@dataclass(frozen=True, slots=True)
class Shortlists:
    """§8.3 + Р-5: раздельные списки вместо ранжирования по модулю.

    responsive_unsigned — следствие Р-18: параметр с direction=unknown даёт
    величину отклика, но не даёт знака. Отправить такую пробу в «ухудшение»
    значило бы предрешить результат, а в «улучшение» — тем более. Она
    диагностически значима и ждёт установления направления.
    """

    shortlist: list[ProbeResponse]
    notable_worsening: list[ProbeResponse]
    responsive_unsigned: list[ProbeResponse]
    in_noise: list[ProbeResponse]


def build_shortlists(responses: list[ProbeResponse], threshold: float) -> Shortlists:
    improving: list[ProbeResponse] = []
    worsening: list[ProbeResponse] = []
    unsigned: list[ProbeResponse] = []
    noise: list[ProbeResponse] = []
    for r in responses:
        if r.delta_index is None or abs(r.delta_index) < threshold:
            noise.append(r)
        elif not r.direction_known:
            unsigned.append(r)
        elif r.delta_index < 0:
            improving.append(r)
        else:
            worsening.append(r)
    improving.sort(key=lambda r: r.delta_index or 0.0)          # сильнее улучшение — выше
    worsening.sort(key=lambda r: -(r.delta_index or 0.0))
    unsigned.sort(key=lambda r: -abs(r.delta_index or 0.0))
    return Shortlists(
        shortlist=improving, notable_worsening=worsening,
        responsive_unsigned=unsigned, in_noise=noise,
    )


def interim_repeat_codes(responses: list[ProbeResponse], threshold: float, top: int = 2) -> list[str]:
    """Промежуточный расчёт для подтверждающего повтора (Р-28).

    Возвращает ТОЛЬКО коды проб. Величины, размеры эффекта и направление не
    отдаются: иначе слепота разбора качества (Р-17) снимается до его закрытия.

    Повторяются самые сильные отклики независимо от знака: пока направление
    параметров не установлено (Р-18), «улучшение» — недоступная категория,
    а подтверждать величину отклика нужно в любом случае.
    """
    lists = build_shortlists(responses, threshold)
    ranked = sorted(
        lists.shortlist + lists.responsive_unsigned,
        key=lambda r: -abs(r.delta_index or 0.0),
    )
    return [r.probe_code for r in ranked[:top]]


# ── Связка кондилографии и формометрии: уровень M синхронизации (§6.2) ───────

@dataclass(frozen=True, slots=True)
class ExcursionMatch:
    status: Literal["matched", "mismatch", "absent"]
    formetric_mm: float | None
    condylar_mm: float | None
    delta_mm: float | None
    tolerance_mm: float
    message: str


def match_excursion(
    formetric_mm: float | None,
    condylar_mm: float | None,
    tolerance_mm: float = 1.0,
) -> ExcursionMatch:
    """MUST §6.2: сверка excursion_mm записи аксиографии и формометрической пробы.

    При превышении допуска связка НЕ строится, `match_status = mismatch` и флаг
    выводится в отчёт: расхождение означает, что пациент выполнил разные движения
    под двумя приборами, и сопоставлять их как одно условие нельзя.

    Источник условной величины — QUANTITY / Maximum excursion distance CADIAX;
    для парных сторон берётся большая, как и печатает прибор.
    """
    if formetric_mm is None or condylar_mm is None:
        return ExcursionMatch(
            "absent", formetric_mm, condylar_mm, None, tolerance_mm,
            "экскурсия задана не для обеих модальностей — связка не строится",
        )
    delta = round(condylar_mm - formetric_mm, 3)
    if abs(delta) <= tolerance_mm:
        return ExcursionMatch("matched", formetric_mm, condylar_mm, delta, tolerance_mm,
                              "экскурсии совпадают в пределах допуска")
    return ExcursionMatch(
        "mismatch", formetric_mm, condylar_mm, delta, tolerance_mm,
        f"расхождение экскурсии {abs(delta):.2f} мм превышает допуск {tolerance_mm} мм: "
        "движения под приборами различались, связка по коду пробы не строится",
    )


def condylar_asymmetry(params: dict[str, float], metric: str) -> float | None:
    """Асимметрия сустава — «суставной» знак когерентности §9.5.

    Возвращает относительную разницу право/лево в процентах. Прибор печатает
    готовые Ratio, но собственный расчёт нужен для метрик, где их нет.
    """
    r, l = params.get(f"{metric}_R"), params.get(f"{metric}_L")
    if r is None or l is None or (abs(r) + abs(l)) == 0:
        return None
    return round(200 * (r - l) / (abs(r) + abs(l)), 2)
