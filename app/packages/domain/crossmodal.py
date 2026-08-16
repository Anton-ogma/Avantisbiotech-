"""Стыковка модальностей и классификация проб (§9.5, §6.2 ТЗ).

Четыре сигнала на пробу — поза, сустав, мышца, сила — сводятся не в один
индекс, а в согласованность между собой (§9.5). ΔMI и ΔSI считаются отдельно
и в PI/RI не суммируются; кондилография тоже отдельный сигнал.

Сила добавлена четвёртой (Р-41): в этом протоколе одноимённые пробы ставятся
на всех четырёх приборах, и держать myoline сессионной характеристикой значило
бы стереть ровно тот эффект, ради которого её и измеряют. Голосовать в
когерентности она при этом не начинает — направление «больше силы лучше» под
пробой не установлено, см. `effects.coherence`.

Классификация «лучшая / худшая / нейтральная» — это описание ИЗМЕРЕННОГО
отклика, а не терапевтическое назначение: в режиме research движок правил
выключен (Р-19), и переход от «проба даёт наибольшее улучшение позы»
к «назначить эту пробу» делает врач, а не система.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .config import ConfigBundle
from .effects import ExcursionMatch, ParamEffect, match_excursion, param_effect
from .indices import response_index

Verdict = Literal["best", "worse", "neutral", "unsigned", "conflicting", "no_posture"]

VERDICT_RU: dict[str, str] = {
    "best": "лучшая по отклику",
    "worse": "ухудшает",
    "neutral": "в пределах шума",
    "unsigned": "отвечает, знак не установлен",
    "conflicting": "конфликт позы и мышцы",
    "no_posture": "поза не измерена под этой пробой",
}


@dataclass(frozen=True, slots=True)
class ModalitySignal:
    """Один из четырёх сигналов §9.5."""

    available: bool
    delta: float | None
    reliable: bool
    detail: str
    params: list[ParamEffect] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ProbeSynthesis:
    probe_code: str
    label_ru: str
    posture: ModalitySignal
    joint: ModalitySignal
    muscle: ModalitySignal
    strength: ModalitySignal
    coherence: str
    verdict: Verdict
    verdict_ru: str
    excursion: ExcursionMatch | None
    rationale: str


def muscle_index(values: dict[str, float], bundle: ConfigBundle) -> float | None:
    """MI — сводная мышечная активность в единицах SDC.

    MUST §9.5: считается ОТДЕЛЬНЫМ индексом и не суммируется в PI/RI.
    """
    contributions: list[float] = []
    for code, value in values.items():
        if not code.startswith("EMG_RMS_"):
            continue
        sdc = bundle.thresholds.sdc(code)
        if sdc:
            contributions.append(abs(value) / sdc)
    if not contributions:
        return None
    return round(sum(contributions) / len(contributions), 4)


def strength_index(values: dict[str, float], bundle: ConfigBundle) -> float | None:
    """SI — сводная изометрическая сила в единицах SDC (Р-41).

    Устроен как MI и по той же причине: ньютоны разных групп мышц несравнимы
    между собой напрямую, а в единицах собственного порога — сравнимы.
    В PI/RI не суммируется: складывать ньютоны с миллиметрами бессмысленно.

    Асимметрия в индекс НЕ входит: она уже безразмерна и имеет собственный
    порог, а сложение «уровня» с «перекосом» дало бы величину, рост которой
    нельзя истолковать.
    """
    contributions: list[float] = []
    for code, value in values.items():
        if not code.startswith("MYO_FORCE_"):
            continue
        sdc = bundle.thresholds.sdc(code)
        if sdc:
            contributions.append(abs(value) / sdc)
    if not contributions:
        return None
    return round(sum(contributions) / len(contributions), 4)


def joint_asymmetry(values: dict[str, float]) -> float | None:
    """Сводная асимметрия мыщелков: среднее по парным метрикам, в процентах.

    Знак «улучшения» здесь задаёт само ТЗ: §9.5 определяет суставной сигнал как
    СИММЕТРИЗАЦИЮ координат мыщелков, то есть снижение |асимметрии| — улучшение.
    Это единственное место, где направление берётся из методики, а не из данных.
    """
    bases = {c[:-2] for c in values if c.endswith(("_R", "_L")) and c.startswith("CDG_")}
    shares: list[float] = []
    for base in bases:
        r, l = values.get(f"{base}_R"), values.get(f"{base}_L")
        if r is None or l is None or (abs(r) + abs(l)) == 0:
            continue
        shares.append(abs(200 * (r - l) / (abs(r) + abs(l))))
    if not shares:
        return None
    return round(sum(shares) / len(shares), 3)


def _split(values: dict[str, float], bundle: ConfigBundle, modality: str) -> dict[str, float]:
    out = {}
    for code, value in values.items():
        spec = bundle.registry.get(code)
        if spec and spec.modality == modality:
            out[code] = value
    return out


def synthesize_probe(
    probe_code: str,
    trial_values: dict[str, float],
    baseline_values: dict[str, float],
    bundle: ConfigBundle,
    *,
    formetric_excursion_mm: float | None = None,
) -> ProbeSynthesis:
    spec = bundle.probes.get(probe_code)
    threshold = bundle.thresholds.sdc("PI") or 1.0
    mi_threshold = bundle.thresholds.sdc("MI") or 1.0

    # ── Поза ─────────────────────────────────────────────────────────────────
    posture_codes = {"formetric", "formetric_dynamic", "pedoscan"}
    trial_posture = {c: v for c, v in trial_values.items()
                     if (s := bundle.registry.get(c)) and s.modality in posture_codes}
    base_posture = {c: v for c, v in baseline_values.items() if c in trial_posture}
    if trial_posture and base_posture:
        effects = [param_effect(c, base_posture[c], trial_posture[c], bundle)
                   for c in sorted(base_posture)]
        deltas = {e.code: e.delta for e in effects}
        ri = response_index(deltas, bundle).total
        signed = sum(1 if e.interpretation == "worsening" else -1 if e.interpretation == "improving" else 0
                     for e in effects)
        delta_posture = None if ri is None else round(ri if signed >= 0 else -ri, 4)
        direction_known = any(e.interpretation is not None for e in effects
                              if e.confidence in ("probable", "reliable"))
        posture = ModalitySignal(
            available=True, delta=delta_posture,
            reliable=delta_posture is not None and abs(delta_posture) >= threshold,
            detail="направление установлено" if direction_known else "направление не установлено",
            params=effects,
        )
    else:
        posture = ModalitySignal(False, None, False, "нет формометрии для этой пробы")
        direction_known = False

    # ── Сустав ───────────────────────────────────────────────────────────────
    a_trial = joint_asymmetry(_split(trial_values, bundle, "condylography"))
    a_base = joint_asymmetry(_split(baseline_values, bundle, "condylography"))
    if a_trial is not None and a_base is not None:
        delta_joint = round(a_trial - a_base, 3)
        joint = ModalitySignal(True, delta_joint, abs(delta_joint) >= 5.0,
                               f"асимметрия {a_base:.1f}% → {a_trial:.1f}%")
    elif a_trial is not None:
        joint = ModalitySignal(True, None, False,
                               f"асимметрия {a_trial:.1f}%, сравнивать не с чем: "
                               "нейтральной кондилографической записи нет")
    else:
        joint = ModalitySignal(False, None, False, "нет кондилографии для этой пробы")

    # ── Мышца ────────────────────────────────────────────────────────────────
    mi_trial = muscle_index(_split(trial_values, bundle, "emg"), bundle)
    mi_base = muscle_index(_split(baseline_values, bundle, "emg"), bundle)
    if mi_trial is not None and mi_base is not None:
        delta_mi = round(mi_trial - mi_base, 4)
        muscle = ModalitySignal(True, delta_mi, abs(delta_mi) >= mi_threshold,
                                f"MI {mi_base:.2f} → {mi_trial:.2f}")
    elif mi_trial is not None:
        muscle = ModalitySignal(True, None, False, f"MI {mi_trial:.2f}, нейтральной ЭМГ нет")
    else:
        muscle = ModalitySignal(False, None, False, "нет ЭМГ для этой пробы")

    # ── Сила ─────────────────────────────────────────────────────────────────
    si_threshold = bundle.thresholds.sdc("SI") or 1.0
    trial_strength = _split(trial_values, bundle, "myoline")
    base_strength = _split(baseline_values, bundle, "myoline")
    si_trial = strength_index(trial_strength, bundle)
    si_base = strength_index(base_strength, bundle)
    asym_trial = trial_strength.get("MYO_ASYM_TRUNK_LAT")
    asym_base = base_strength.get("MYO_ASYM_TRUNK_LAT")
    asym_note = ("" if asym_trial is None or asym_base is None else
                 f"; асимметрия {asym_base:+.1f}% → {asym_trial:+.1f}%")
    if si_trial is not None and si_base is not None:
        delta_si = round(si_trial - si_base, 4)
        strength = ModalitySignal(
            True, delta_si, abs(delta_si) >= si_threshold,
            f"SI {si_base:.2f} → {si_trial:.2f}{asym_note}",
            params=[param_effect(c, base_strength[c], trial_strength[c], bundle)
                    for c in sorted(set(base_strength) & set(trial_strength))],
        )
    elif si_trial is not None:
        strength = ModalitySignal(True, None, False,
                                  f"SI {si_trial:.2f}, нейтрального измерения силы нет")
    else:
        strength = ModalitySignal(False, None, False, "нет myoline для этой пробы")

    # ── Когерентность и вердикт ──────────────────────────────────────────────
    from .effects import coherence as coherence_fn

    # Сила голосует только если её направление установлено в реестре. Пока оно
    # unknown, знак «согласия» назначить нечем (Р-18, Р-41).
    strength_votes = any(
        (s := bundle.registry.get(c)) and s.direction != "unknown"
        for c in trial_strength if c.startswith("MYO_FORCE_")
    )
    coh = coherence_fn(posture.delta, joint.delta, muscle.delta, threshold,
                       strength.delta, strength_votes=strength_votes)

    excursion = None
    if spec and spec.requires_excursion:
        excursion = match_excursion(
            formetric_excursion_mm,
            max((v for c, v in trial_values.items() if c.startswith("CDG_MAX_EXCURSION")), default=None),
        )

    verdict, rationale = _classify(posture, muscle, strength, coh, direction_known,
                                   threshold, mi_threshold, si_threshold)

    return ProbeSynthesis(
        probe_code=probe_code,
        label_ru=spec.label_ru if spec else probe_code,
        posture=posture, joint=joint, muscle=muscle, strength=strength,
        coherence=coh, verdict=verdict, verdict_ru=VERDICT_RU[verdict],
        excursion=excursion, rationale=rationale,
    )


def _classify(
    posture: ModalitySignal, muscle: ModalitySignal, strength: ModalitySignal, coh: str,
    direction_known: bool, threshold: float, mi_threshold: float, si_threshold: float,
) -> tuple[Verdict, str]:
    if not posture.available:
        # Отличать «поза не измерена» от «поза не изменилась» обязательно:
        # свалить их в одну корзину значит выдать отсутствие данных за результат.
        return "no_posture", (
            "под этой пробой нет формометрии — вердикт по позе не выносится. "
            "Другие модальности показаны, но сами по себе ранжирование не задают"
        )
    if posture.delta is None:
        return "neutral", "поза измерена, но отклик не вычислен"
    if abs(posture.delta) < threshold:
        return "neutral", (
            f"|Δ| = {abs(posture.delta):.2f} ниже порога {threshold}: значение в шуме "
            "и в ранжирование не идёт (§9.3)"
        )
    if not direction_known:
        return "unsigned", (
            "отклик достоверен по величине, но ни один изменившийся параметр не имеет "
            "установленного направления — назначить знак нечем (Р-18)"
        )
    if coh == "posture_muscle_conflict":
        return "conflicting", (
            "поза улучшается, но мышечная активность растёт выше порога: "
            "конфликт сигналов, одновременное назначение не выдаётся (§9.5, §11)"
        )
    if posture.delta < 0:
        parts = ["поза улучшается достоверно"]
        if muscle.available and muscle.delta is not None and muscle.delta <= mi_threshold:
            parts.append("мышечная активность не растёт")
        if coh == "full":
            parts.append("все измеренные сигналы сходятся")
        if strength.available and strength.delta is not None and abs(strength.delta) >= si_threshold:
            # Сила показывается всегда, но без знака «лучше/хуже»: направление
            # под пробой не установлено, и вердикт на неё не опирается (Р-41).
            parts.append(f"сила меняется на {strength.delta:+.2f} SDC, "
                         "направление не установлено")
        return "best", "; ".join(parts)
    return "worse", "поза ухудшается достоверно — в рекомендации не идёт никогда (Р-5)"


def rank_probes(items: list[ProbeSynthesis]) -> dict[str, list[ProbeSynthesis]]:
    """Раскладка по вердиктам с сортировкой внутри каждой группы."""
    buckets: dict[str, list[ProbeSynthesis]] = {
        "best": [], "worse": [], "conflicting": [], "unsigned": [], "neutral": [], "no_posture": [],
    }
    for item in items:
        buckets[item.verdict].append(item)
    buckets["best"].sort(key=lambda p: p.posture.delta or 0.0)
    buckets["worse"].sort(key=lambda p: -(p.posture.delta or 0.0))
    buckets["unsigned"].sort(key=lambda p: -abs(p.posture.delta or 0.0))
    return buckets
