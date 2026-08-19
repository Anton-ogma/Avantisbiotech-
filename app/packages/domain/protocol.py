"""Протокол сессии: машина состояний, план, валидаторы (§8.1; Р-28, Р-29, Р-31).

Принцип Р-31: валидатор, срабатывающий после ухода пациента, ничего не
предотвращает. Поэтому проверки полноты и порядка живут на утверждении плана,
до первой пробы, а не на выходе из probes_running.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Literal

from .config import ConfigBundle, ProbeSpec

Status = Literal[
    "prepared", "plan_approved", "baseline_recorded", "probes_running",
    "imported", "quality_reviewed", "shortlist_confirmed", "analyzed", "reported",
]

STATUS_ORDER: tuple[Status, ...] = (
    "prepared", "plan_approved", "baseline_recorded", "probes_running",
    "imported", "quality_reviewed", "shortlist_confirmed", "analyzed", "reported",
)

#: Переходы односторонние, КРОМЕ цикла probes_running ⇄ imported (Р-28):
#: подтверждающий повтор — второй проход, иначе он невыразим в машине.
CYCLIC: frozenset[tuple[str, str]] = frozenset({("imported", "probes_running")})

GROUP_ORDER: tuple[str, ...] = ("reference", "diagnostic", "podal", "therapeutic")


class ProtocolError(ValueError):
    """Нарушение протокола. Блокирует переход, а не помечает постфактум."""


@dataclass(frozen=True, slots=True)
class PlannedProbe:
    probe_code: str
    role: str
    position: int
    pass_no: int = 1


@dataclass(slots=True)
class Violation:
    code: str
    message: str
    blocking: bool = True


def can_transition(current: Status, target: Status) -> bool:
    if (current, target) in CYCLIC:
        return True
    return STATUS_ORDER.index(target) == STATUS_ORDER.index(current) + 1


def assert_transition(current: Status, target: Status) -> None:
    if not can_transition(current, target):
        raise ProtocolError(
            f"переход {current} → {target} не разрешён; допустим только следующий "
            f"по порядку либо цикл imported → probes_running (Р-28)"
        )


# ── Валидаторы плана: проверяются на prepared → plan_approved (Р-31) ──────────

def validate_plan(
    planned: list[PlannedProbe],
    bundle: ConfigBundle,
    *,
    study_mode: bool,
    lld_measured: bool,
    randomization_scheme: str,
    randomization_seed: int | None,
) -> list[Violation]:
    v: list[Violation] = []
    specs: list[tuple[PlannedProbe, ProbeSpec]] = []
    for p in sorted(planned, key=lambda x: (x.pass_no, x.position)):
        spec = bundle.probes.get(p.probe_code)
        if spec is None:
            v.append(Violation("unknown_probe", f"проба {p.probe_code} отсутствует в реестре"))
            continue
        specs.append((p, spec))

    # #2 порядок групп: reference → diagnostic → podal → therapeutic.
    # Контрольные пробы идут внутри своей группы (Р-29), поэтому ранжируем по
    # группе реестра, а не по role.
    def rank(spec: ProbeSpec) -> int:
        if spec.role == "reference":
            return 0
        if spec.role == "therapeutic":
            return 3
        if spec.group == "podal":
            return 2
        return 1

    for pass_no in sorted({p.pass_no for p, _ in specs}):
        seq = [(p, s) for p, s in specs if p.pass_no == pass_no]
        ranks = [rank(s) for _, s in seq if not s.is_neutral]
        if ranks != sorted(ranks):
            v.append(Violation(
                "group_order",
                f"проход {pass_no}: нарушен порядок групп "
                f"{' → '.join(GROUP_ORDER)}; терапевтическая проба до диагностических "
                "не допускается",
            ))

    # #8 нейтраль минимум трижды: начало, середина, конец
    neutrals = [p.position for p, s in specs if s.is_neutral and p.pass_no == 1]
    if len(neutrals) < 3:
        v.append(
            Violation("neutral_count", f"нейтраль запланирована {len(neutrals)} раз, нужно ≥3"))
    else:
        last = max(p.position for p, _ in specs if p.pass_no == 1)
        if min(neutrals) > 1 or max(neutrals) < last:
            v.append(Violation(
                "neutral_placement",
                "нейтраль должна стоять в начале, середине и конце прохода",
            ))

    # #9 sham обязателен в исследовательской сессии с терапевтической пробой (Р-15)
    if study_mode:
        therapeutic_groups = {s.group for _, s in specs if s.role == "therapeutic"}
        sham_groups = {s.shams_group for _, s in specs if s.shams_group}
        for group in sorted(therapeutic_groups - sham_groups):
            v.append(Violation(
                "sham_missing",
                f"группа {group}: терапевтическая проба без sham. Без sham изменение "
                "объясняется временем, вниманием и ожиданием эффекта",
            ))

    # #10 seed при любой схеме кроме none (Р-16)
    if randomization_scheme != "none" and randomization_seed is None:
        v.append(
            Violation("seed_missing", f"схема {randomization_scheme} требует randomization_seed"))

    # #7 компенсация длины ног — условие сессии, до первой пробы (Р-33)
    if not lld_measured:
        v.append(
            Violation("lld_missing", "разница длины ног не измерена, компенсация не зафиксирована"))

    return v


def randomize_within_groups(
    planned: list[PlannedProbe], bundle: ConfigBundle, seed: int
) -> list[PlannedProbe]:
    """Рандомизация внутри группы (§8.1.2). Sham перемешивается наравне с активными
    пробами своей группы (Р-29): фиксированная позиция вычисляется и пациентом,
    и оператором, и смысл sham исчезает.

    Воспроизводима из seed — иначе эффект порядка нельзя проверить (Р-16).
    """
    rng = random.Random(seed)
    fixed: list[PlannedProbe] = []
    buckets: dict[tuple[int, str], list[PlannedProbe]] = {}
    for p in sorted(planned, key=lambda x: (x.pass_no, x.position)):
        spec = bundle.probes.get(p.probe_code)
        if spec is None or spec.is_neutral or spec.role == "reference":
            fixed.append(p)                      # нейтраль не перемешивается
            continue
        buckets.setdefault((p.pass_no, spec.group), []).append(p)

    result = list(fixed)
    for key in sorted(buckets):
        group = buckets[key]
        positions = sorted(p.position for p in group)
        shuffled = list(group)
        rng.shuffle(shuffled)
        result.extend(
            PlannedProbe(p.probe_code, p.role, pos, p.pass_no)
            for p, pos in zip(shuffled, positions, strict=True)
        )
    return sorted(result, key=lambda x: (x.pass_no, x.position))


# ── Валидаторы исполнения: проверяются на приёме каждой пробы (Р-31) ──────────

@dataclass(frozen=True, slots=True)
class TrialFact:
    probe_code: str
    position: int
    pass_no: int
    settle_sec_actual: int
    minutes_since_prev_group: float | None
    excursion_mm: float | None
    effort_achieved_pct: float | None


def validate_trial(fact: TrialFact, bundle: ConfigBundle) -> list[Violation]:
    spec = bundle.probes.get(fact.probe_code)
    if spec is None:
        return [Violation("unknown_probe", f"проба {fact.probe_code} отсутствует в реестре")]
    v: list[Violation] = []
    if fact.settle_sec_actual < spec.settle_sec:                                    # #3
        v.append(Violation(
            "settle", f"выдержка {fact.settle_sec_actual}с меньше требуемой {spec.settle_sec}с"
        ))
    if (                                                                            # #4
        spec.carryover_min > 0
        and fact.minutes_since_prev_group is not None
        and fact.minutes_since_prev_group < spec.carryover_min
    ):
        v.append(Violation(
            "washout",
            f"washout {fact.minutes_since_prev_group:.1f} мин меньше {spec.carryover_min} мин",
        ))
    if spec.requires_excursion and fact.excursion_mm is None:                       # #6
        v.append(Violation("excursion", "для эксцентрической пробы обязателен excursion_mm"))
    if spec.requires_effort and fact.effort_achieved_pct is None:                   # #6
        v.append(Violation("effort", "для пробы со сжатием обязателен effort.achieved_pct"))
    return v


@dataclass(slots=True)
class Deviation:
    kind: Literal["missing", "extra", "out_of_order", "settle", "washout"]
    probe_code: str
    reason: str


def reconcile_with_plan(
    planned: list[PlannedProbe], actual: list[TrialFact]
) -> list[Deviation]:
    """Сверка факта с планом (Р-29). Расхождения — данные, а не ошибка:
    ГОСТ Р ИСО 14155 требует прослеживаемости протокольных отклонений."""
    dev: list[Deviation] = []
    plan_keys = [(p.pass_no, p.probe_code) for p in planned]
    fact_keys = [(f.pass_no, f.probe_code) for f in actual]
    for key in plan_keys:
        if key not in fact_keys:
            dev.append(
                Deviation("missing", key[1], f"проход {key[0]}: запланирована, не выполнена"))
    for key in fact_keys:
        if key not in plan_keys:
            dev.append(Deviation("extra", key[1], f"проход {key[0]}: выполнена вне плана"))
    planned_order = [k for k in plan_keys if k in fact_keys]
    actual_order = [k for k in fact_keys if k in plan_keys]
    if planned_order != actual_order:
        dev.append(Deviation("out_of_order", "-", "фактический порядок не совпал с планом"))
    return dev
