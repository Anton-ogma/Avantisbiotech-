"""Оркестратор анализа сессии (§9 ТЗ).

MUST §3: чистая функция. Никакого I/O, никаких системных часов — всё аргументами.
MUST §4 инвариант 2: тот же вход и те же пять версий дают побайтово тот же результат.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from .config import ConfigBundle
from .drift import NeutralObservation, baseline_drift, fit_baseline
from .effects import (
    ParamEffect,
    ProbeResponse,
    build_shortlists,
    combined_verdict,
    interim_repeat_codes,
    param_effect,
)
from .hashing import input_hash
from .indices import compute_z, postural_index, response_index


@dataclass(frozen=True, slots=True)
class TrialInput:
    """Одна проба с каноническими значениями. t — секунды от начала сессии."""

    trial_id: str
    probe_code: str
    role: str
    pass_no: int
    t: float
    is_neutral: bool
    values: dict[str, float]
    quality_flags: list[str] = field(default_factory=list)
    excluded: bool = False


@dataclass(frozen=True, slots=True)
class SessionInput:
    session_id: str
    patient_ref: str
    neutral_definition: str
    study_mode: bool
    trials: list[TrialInput]


@dataclass(slots=True)
class AnalysisResult:
    session_id: str
    index_kind: Literal["RI", "PI"]
    versions: dict[str, str]
    input_hash: str
    baseline: dict[str, float]
    drift: dict[str, Any]
    low_confidence: bool
    responses: list[dict[str, Any]]
    shortlist: list[str]
    notable_worsening: list[str]
    responsive_unsigned: list[str]
    in_noise: list[str]
    combined: list[dict[str, Any]]
    warnings: list[str]
    interim: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _effects_to_dict(effects: list[ParamEffect], bundle: ConfigBundle) -> list[dict[str, Any]]:
    out = []
    for e in effects:
        spec = bundle.registry.get(e.code)
        out.append({
            "code": e.code,
            "label_ru": spec.label_ru if spec else e.code,
            "unit": spec.unit if spec else "",
            "domain": spec.domain if spec else "unknown",
            "baseline": e.baseline,
            "value": e.value,
            "delta": e.delta,
            "sdc": e.sdc,
            "effect_size": e.effect_size,
            "confidence": e.confidence,
            "direction": e.direction,
            "interpretation": e.interpretation,
        })
    return out


def analyze(session: SessionInput, bundle: ConfigBundle, *, interim: bool = False) -> AnalysisResult:
    warnings: list[str] = []
    if bundle.thresholds.is_demo:
        # MUST §10: предупреждение о некалиброванных порогах — на всех экранах.
        warnings.append(
            "Пороги некалиброваны (source=demo). Суждения о значимости недействительны "
            "до выпуска собственного SDC режимом повторяемости (Этап 1.5)."
        )
    if bundle.norms.empty:
        warnings.append("Нормы не заданы: PI не вычисляется, используется RI (Р-13).")

    usable = [t for t in session.trials if not t.excluded]
    neutrals = [NeutralObservation(t.t, t.values) for t in usable if t.is_neutral]
    if not neutrals:
        raise ValueError("в сессии нет ни одной пригодной нейтрали")

    model = fit_baseline(neutrals)
    drift = baseline_drift(neutrals, model, bundle)
    if not drift.computable and drift.reason:
        warnings.append(f"Дрейф нейтрали не оценён: {drift.reason}.")

    index_kind: Literal["RI", "PI"] = "PI" if not bundle.norms.empty else "RI"

    responses: list[ProbeResponse] = []
    for trial in usable:
        if trial.is_neutral:
            continue
        baseline_at_t = model.at(trial.t)          # поправка на позицию во времени
        effects = [
            param_effect(code, baseline_at_t[code], value, bundle)
            for code, value in sorted(trial.values.items())
            if code in baseline_at_t
        ]
        deltas = {e.code: e.delta for e in effects}

        if index_kind == "PI":
            base_idx = postural_index(baseline_at_t, bundle).total
            trial_idx = postural_index(trial.values, bundle).total
            delta_index = None if base_idx is None or trial_idx is None else round(trial_idx - base_idx, 6)
        else:
            # RI по построению уже относительно нейтрали: чем больше, тем сильнее
            # отклик. Знак берём у доменно-взвешенной суммы Δ, чтобы отличить
            # улучшение от ухудшения там, где направление известно.
            ri = response_index(deltas, bundle).total
            if ri is None:
                delta_index = None
            else:
                # Знак берём только у параметров с ИЗВЕСТНЫМ направлением (Р-18).
                # Если таких нет, величина остаётся, а знак не назначается —
                # предрешать результат нельзя.
                signed = sum(
                    1 if e.interpretation == "worsening" else -1 if e.interpretation == "improving" else 0
                    for e in effects
                )
                delta_index = round(ri if signed >= 0 else -ri, 6)

        best_conf = "noise"
        for e in effects:
            if e.confidence == "reliable":
                best_conf = "reliable"
                break
            if e.confidence == "probable":
                best_conf = "probable"

        direction_known = any(
            e.interpretation is not None for e in effects
            if e.confidence in ("probable", "reliable")
        )
        responses.append(ProbeResponse(
            probe_code=trial.probe_code,
            pass_no=trial.pass_no,
            delta_index=delta_index,
            index_kind=index_kind,
            confidence=best_conf,  # type: ignore[arg-type]
            params=effects,
            confirmed=trial.pass_no > 1,
            direction_known=direction_known,
        ))

    threshold = bundle.thresholds.sdc("PI") or 1.0
    lists = build_shortlists(responses, threshold)

    # §8.3: в шорт-лист попадает только проба, подтверждённая вторым проходом.
    confirmed_codes = {r.probe_code for r in responses if r.pass_no > 1 and r.improving}
    shortlist_codes = [
        r.probe_code for r in lists.shortlist
        if r.pass_no == 1 and (r.probe_code in confirmed_codes or interim)
    ]
    if lists.responsive_unsigned:
        warnings.append(
            f"{len(lists.responsive_unsigned)} проб дали достоверный отклик, но знак не "
            "назначен: направление параметров ещё не установлено (direction=unknown, Р-18). "
            "Величина зафиксирована, интерпретация ожидает подтверждающего анализа."
        )
    if not interim and not confirmed_codes and lists.shortlist:
        warnings.append(
            "Ни одна проба не подтверждена вторым проходом — шорт-лист пуст. "
            "Неподтверждённые пробы в рекомендации не идут (§8.3)."
        )

    combined = _combined_probes(responses, threshold)

    payload = {
        "session": session.session_id,
        "neutral_definition": session.neutral_definition,
        "trials": [
            {"probe": t.probe_code, "pass": t.pass_no, "t": t.t,
             "values": {k: v for k, v in sorted(t.values.items())}}
            for t in sorted(usable, key=lambda x: (x.pass_no, x.t))
        ],
    }

    return AnalysisResult(
        session_id=session.session_id,
        index_kind=index_kind,
        versions=bundle.versions,
        input_hash=input_hash(payload, bundle.versions),
        baseline={k: round(v, 6) for k, v in sorted(model.at(0.0).items())},
        drift={
            "raw": drift.raw_drift,
            "residual": drift.residual_drift,
            "worst_param": drift.worst_param,
            "computable": drift.computable,
            "reason": drift.reason,
        },
        low_confidence=drift.low_confidence,
        responses=[{
            "probe_code": r.probe_code,
            "pass_no": r.pass_no,
            "delta_index": r.delta_index,
            "index_kind": r.index_kind,
            "confidence": r.confidence,
            "confirmed": r.confirmed,
            "direction_known": r.direction_known,
            "params": _effects_to_dict(r.params, bundle),
        } for r in responses],
        shortlist=shortlist_codes,
        notable_worsening=[r.probe_code for r in lists.notable_worsening],
        responsive_unsigned=[r.probe_code for r in lists.responsive_unsigned],
        in_noise=[r.probe_code for r in lists.in_noise],
        combined=combined,
        warnings=warnings,
        interim=interim,
    )


def _combined_probes(responses: list[ProbeResponse], threshold: float) -> list[dict[str, Any]]:
    """§9.7: вердикт комбинированной пробы COMBI_<A>_PLUS_<B>."""
    by_code = {r.probe_code: r for r in responses if r.pass_no == 1}
    out: list[dict[str, Any]] = []
    for code, r in sorted(by_code.items()):
        if not code.startswith("COMBI_") or "_PLUS_" not in code:
            continue
        a_code, b_code = code[len("COMBI_"):].split("_PLUS_", 1)
        a, b = by_code.get(a_code), by_code.get(b_code)
        if not a or not b or a.delta_index is None or b.delta_index is None or r.delta_index is None:
            continue
        out.append({
            "code": code,
            "a": a_code, "b": b_code,
            "delta_a": a.delta_index, "delta_b": b.delta_index, "delta_ab": r.delta_index,
            "verdict": combined_verdict(r.delta_index, a.delta_index, b.delta_index, threshold),
        })
    return out


def interim_plan(session: SessionInput, bundle: ConfigBundle, top: int = 2) -> list[str]:
    """Р-28: оператору отдаются ТОЛЬКО коды проб к повтору, без величин."""
    result = analyze(session, bundle, interim=True)
    responses = [
        ProbeResponse(
            probe_code=r["probe_code"], pass_no=r["pass_no"], delta_index=r["delta_index"],
            index_kind=r["index_kind"], confidence=r["confidence"], params=[],
            direction_known=r.get("direction_known", True),
        )
        for r in result.responses if r["pass_no"] == 1
    ]
    return interim_repeat_codes(responses, bundle.thresholds.sdc("PI") or 1.0, top)
