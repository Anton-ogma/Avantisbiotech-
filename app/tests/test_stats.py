"""Статистика когортного слоя (§9.8а)."""
import random

from domain.stats import (
    benjamini_hochberg, multivariate_permutation, one_sample_permutation, response_axes,
)


def test_fdr_is_monotone_and_bounded():
    p = {"a": 0.001, "b": 0.01, "c": 0.04, "d": 0.9}
    res = benjamini_hochberg(p, q=0.05)
    qs = [r.q_value for r in res]
    assert qs == sorted(qs)
    assert all(r.q_value >= r.p_value for r in res)


def test_multivariate_beats_corrected_univariate_on_weak_consistent_shift():
    """Обоснование Р-35 в его ТОЧНОЙ формулировке.

    Слабый согласованный сдвиг во всех шести параметрах: по отдельности каждый
    лежит у порога, поправка на множественность гасит ВСЕ. Совместный тест
    отвергает нулевую гипотезу уверенно. Выигрыш — от агрегации и от одной
    проверки вместо шести, а не от коррелированности как таковой.
    """
    rng = random.Random(21)
    sdc = {c: 2.0 for c in "ABCDEF"}
    vectors = [{c: -0.7 + rng.gauss(0, 1.2) for c in sdc} for _ in range(14)]

    uni = {c: one_sample_permutation([v[c] for v in vectors], 4000, 5) for c in sdc}
    survived = [r.code for r in benjamini_hochberg(uni) if r.significant]
    _, p_mv = multivariate_permutation(vectors, sdc, 4000, 5)

    assert survived == []          # ни один одномерный не пережил поправку
    assert p_mv < 0.01             # совместный тест уверенно значим


def test_multivariate_null_is_calibrated():
    """Тест не должен «находить» эффект там, где его нет: при нулевом сдвиге
    p распределён равномерно, а не смещён к нулю."""
    rng = random.Random(99)
    sdc = {c: 2.0 for c in "ABCD"}
    hits = 0
    for trial in range(20):
        vectors = [{c: rng.gauss(0, 1.0) for c in sdc} for _ in range(12)]
        _, p = multivariate_permutation(vectors, sdc, 800, trial)
        hits += p < 0.05
    assert hits <= 3               # ложных срабатываний около номинала


def test_response_axes_find_shared_structure():
    rng = random.Random(3)
    sdc = {c: 2.0 for c in "ABCD"}
    vectors = []
    for _ in range(25):
        shared = rng.gauss(0, 1.2)
        vectors.append({c: shared + rng.gauss(0, 0.3) for c in sdc})
    axes = response_axes(vectors, sdc)
    assert axes and axes[0].explained_share > 0.6      # одна доминирующая ось
    assert all(abs(v) > 0.3 for v in axes[0].loadings.values())
