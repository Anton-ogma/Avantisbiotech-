"""Табличные тесты алгоритмов: z, PI, RI, effect size, вердикты, когерентность (§16)."""
import pytest
from domain.config import load_bundle
from domain.drift import NeutralObservation, baseline_drift, fit_baseline
from domain.effects import (
    ProbeResponse, build_shortlists, classify, coherence, combined_verdict, param_effect,
)
from domain.indices import postural_index, response_index, z_score
from domain.reliability import detectable_effect, icc_2_1, passport


def test_pi_is_none_without_norms(bundle):
    """Р-13: отсутствие норм не блокирует; PI не определён, а не равен нулю."""
    assert postural_index({"PELVIC_TILT": 12.0}, bundle).total is None


def test_ri_works_without_norms(bundle):
    ri = response_index({"PELVIC_TILT": 5.0}, bundle)
    assert ri.total is not None and ri.total > 0


def test_ri_uses_magnitude_not_sign(bundle):
    """RI по модулю: параметр с direction=unknown входит наравне с остальными."""
    a = response_index({"PELVIC_TILT": 5.0}, bundle).total
    b = response_index({"PELVIC_TILT": -5.0}, bundle).total
    assert a == b


@pytest.mark.parametrize("effect,expected", [(0.0, "noise"), (0.99, "noise"), (1.0, "probable"),
                                            (1.99, "probable"), (2.0, "reliable"), (None, "undefined")])
def test_effect_classification(effect, expected):
    assert classify(effect) == expected


def test_unknown_direction_gets_no_interpretation(bundle):
    """Р-18: знак не интерпретируется, пока направление не установлено."""
    e = param_effect("PELVIC_TILT", 10.0, 20.0, bundle)   # direction=unknown
    assert e.confidence == "reliable"
    assert e.interpretation is None


def test_known_direction_gets_interpretation(bundle):
    e = param_effect("LATERAL_DEVIATION_RMS", 10.0, 4.0, bundle)  # higher_worse
    assert e.interpretation == "improving"


@pytest.mark.parametrize(
    "d_ab,d_a,d_b,expected",
    [
        (-1.0, -5.0, -4.0, "conflict"),      # хуже лучшего одиночного
        (-12.0, -5.0, -4.0, "synergistic"),  # лучше суммы
        (-5.0, -5.0, -0.1, "dominant"),      # работает один уровень
        (-9.0, -5.0, -4.0, "additive"),      # вклады сложились
        (-6.8, -5.0, -4.0, "indeterminate"), # между dominant и additive
    ],
)
def test_combined_verdict_precedence(d_ab, d_a, d_b, expected):
    """Р-4: порядок проверки нормативен, условия пересекаются."""
    assert combined_verdict(d_ab, d_a, d_b, threshold=1.0) == expected


def test_conflict_wins_over_additive():
    """conflict проверяется первым — безопасная сторона (§11 запрещает оба уровня)."""
    # ΔPI(AB)=+3 = сумма (-1)+(+4), но хуже лучшего (-1) → конфликт
    assert combined_verdict(3.0, -1.0, 4.0, threshold=1.0) == "conflict"


def test_coherence_renamed_value():
    """Р-6: §9.5 conflict → posture_muscle_conflict."""
    assert coherence(-3.0, None, 3.0, threshold=1.0) == "posture_muscle_conflict"


def test_shortlist_separates_unsigned():
    """Р-5 + Р-18: отклик без установленного направления не идёт ни в улучшение,
    ни в ухудшение — назначить ему знак нечем."""
    rs = [
        ProbeResponse("A", 1, -3.0, "RI", "reliable", [], direction_known=True),
        ProbeResponse("B", 1, 3.0, "RI", "reliable", [], direction_known=True),
        ProbeResponse("C", 1, 4.0, "RI", "reliable", [], direction_known=False),
        ProbeResponse("D", 1, 0.2, "RI", "noise", [], direction_known=True),
    ]
    lists = build_shortlists(rs, threshold=1.0)
    assert [r.probe_code for r in lists.shortlist] == ["A"]
    assert [r.probe_code for r in lists.notable_worsening] == ["B"]
    assert [r.probe_code for r in lists.responsive_unsigned] == ["C"]
    assert [r.probe_code for r in lists.in_noise] == ["D"]


def test_drift_needs_no_norms(bundle):
    """Р-30: дрейф в пространстве параметров, нормированный на SDC."""
    ns = [NeutralObservation(0, {"PELVIC_TILT": 10.0}),
          NeutralObservation(600, {"PELVIC_TILT": 14.0})]
    d = baseline_drift(ns, fit_baseline(ns), bundle)
    assert d.computable
    assert d.raw_drift == pytest.approx(4.0 / 2.5, rel=1e-6)


def test_linear_drift_is_corrected_not_penalised(bundle):
    """Р-30: флаг по остатку после поправки, а не по всей величине."""
    ns = [NeutralObservation(t, {"PELVIC_TILT": 10.0 + t * 0.005}) for t in (0, 600, 1200)]
    d = baseline_drift(ns, fit_baseline(ns), bundle)
    assert d.raw_drift > 1.0            # сырой дрейф выше порога
    assert d.residual_drift == pytest.approx(0.0, abs=1e-9)
    assert d.low_confidence is False    # но он линеен и скомпенсирован


def test_icc_and_sdc():
    rows = [[45.1, 45.6], [38.2, 37.9], [52.0, 52.8], [41.3, 40.9], [47.7, 48.2], [35.5, 35.1]]
    icc, lo, hi = icc_2_1(rows)
    assert icc is not None and icc > 0.95
    assert lo is not None and lo < icc < hi
    p = passport("X", rows)
    assert p.sdc is not None and p.sdc > 0
    assert detectable_effect(p.sdc, 30) < p.sdc     # больше n — меньше детектируемый сдвиг


def test_z_score():
    assert z_score(12.0, 10.0, 2.0) == 1.0
    with pytest.raises(ValueError):
        z_score(1.0, 0.0, 0.0)
