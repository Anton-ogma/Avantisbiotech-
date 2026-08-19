"""Статистика для когортного слоя (§9.8а, слой 3; Р-14, Р-35).

Ключевое решение Р-35: основная единица анализа — ВЕКТОР отклика, а не набор
скаляров. Одномерные тесты остаются рядом, а не вместо.

Откуда берётся выигрыш (проверено tests/test_stats.py): многомерный тест
агрегирует слабые СОГЛАСОВАННЫЕ сдвиги и платит за одну проверку вместо p.
Когда эффект присутствует во многих параметрах, но каждый по отдельности лежит
у порога, поправка на множественность гасит все — а совместный тест уверенно
отвергает нулевую гипотезу.

Чего этот тест НЕ делает: не использует ковариационную структуру. Статистика —
евклидова норма среднего вектора, без обеления. Учёт ковариации (в духе
Хотеллинга) даёт дополнительный выигрыш, когда направление эффекта отличается
от главной оси шума, и это следующий шаг, а не текущее поведение.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FDRResult:
    code: str
    p_value: float
    q_value: float
    significant: bool


def benjamini_hochberg(p_values: dict[str, float], q: float = 0.05) -> list[FDRResult]:
    """Контроль частоты ложных обнаружений по ВСЕМУ семейству проверенных сочетаний,
    а не по отобранным после просмотра (§6 исследовательского контура)."""
    items = sorted(p_values.items(), key=lambda kv: kv[1])
    m = len(items)
    if m == 0:
        return []
    adjusted: list[float] = []
    prev = 1.0
    for i in range(m - 1, -1, -1):
        val = min(prev, items[i][1] * m / (i + 1))
        adjusted.append(val)
        prev = val
    adjusted.reverse()
    return [
        FDRResult(code=code, p_value=p, q_value=round(adj, 6), significant=adj <= q)
        for (code, p), adj in zip(items, adjusted, strict=True)
    ]


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs)


def one_sample_permutation(deltas: list[float], iterations: int, seed: int) -> float:
    """Перестановочный тест знака для одного параметра. Без допущения о нормальности —
    при n порядка десятков это существеннее, чем кажется."""
    n = len(deltas)
    if n < 3:
        return 1.0
    observed = abs(_mean(deltas))
    rng = random.Random(seed)
    hits = 0
    for _ in range(iterations):
        flipped = [d if rng.random() < 0.5 else -d for d in deltas]
        if abs(_mean(flipped)) >= observed:
            hits += 1
    return (hits + 1) / (iterations + 1)


def multivariate_permutation(
    vectors: list[dict[str, float]], sdc: dict[str, float], iterations: int = 5000, seed: int = 1
) -> tuple[float, float]:
    """Многомерный перестановочный тест на векторе Δ (Р-35).

    Статистика — евклидова норма среднего вектора в единицах SDC; нулевое
    распределение строится перестановкой знаков ЦЕЛОГО вектора, что сохраняет
    межпараметрическую зависимость и делает тест корректным при субъектных
    эффектах. Возвращает (статистика, p).
    """
    codes = sorted({c for v in vectors for c in v} & set(sdc))
    if not codes or len(vectors) < 3:
        return 0.0, 1.0

    def stat(sample: list[dict[str, float]]) -> float:
        acc = 0.0
        for code in codes:
            vals = [v[code] / sdc[code] for v in sample if code in v]
            if vals:
                acc += _mean(vals) ** 2
        return math.sqrt(acc)

    observed = stat(vectors)
    rng = random.Random(seed)
    hits = 0
    for _ in range(iterations):
        flipped = [
            {c: (val if rng.random() < 0.5 else -val) for c, val in v.items()} for v in vectors
        ]
        if stat(flipped) >= observed:
            hits += 1
    return round(observed, 6), (hits + 1) / (iterations + 1)


@dataclass(frozen=True, slots=True)
class ResponseAxis:
    index: int
    explained_share: float
    loadings: dict[str, float]


def response_axes(
    vectors: list[dict[str, float]], sdc: dict[str, float], max_axes: int = 3
) -> list[ResponseAxis]:
    """Оси отклика: главные компоненты матрицы Δ, нормированной на SDC (Р-35).

    «Есть воспроизводимая ось изменения» — гораздо более убедительная форма
    находки, чем «параметр X изменился»: одномерный подход с поправкой такую
    структуру теряет по построению.

    Степенной метод с дефляцией: зависимостей не тянет, для десятков параметров
    достаточно.
    """
    codes = sorted({c for v in vectors for c in v} & set(sdc))
    n, p = len(vectors), len(codes)
    if n < 3 or p < 2:
        return []

    matrix = [[v.get(c, 0.0) / sdc[c] for c in codes] for v in vectors]
    means = [sum(row[j] for row in matrix) / n for j in range(p)]
    centered = [[row[j] - means[j] for j in range(p)] for row in matrix]
    cov = [
        [sum(centered[i][a] * centered[i][b] for i in range(n)) / (n - 1) for b in range(p)]
        for a in range(p)
    ]
    total_var = sum(cov[i][i] for i in range(p))
    if total_var <= 0:
        return []

    axes: list[ResponseAxis] = []
    rng = random.Random(7)
    for k in range(min(max_axes, p)):
        vec = [rng.random() - 0.5 for _ in range(p)]
        eigenvalue = 0.0
        for _ in range(300):
            nxt = [sum(cov[a][b] * vec[b] for b in range(p)) for a in range(p)]
            norm = math.sqrt(sum(x * x for x in nxt))
            if norm < 1e-12:
                break
            nxt = [x / norm for x in nxt]
            if sum(abs(nxt[i] - vec[i]) for i in range(p)) < 1e-10:
                vec = nxt
                eigenvalue = norm
                break
            vec, eigenvalue = nxt, norm
        if eigenvalue <= 1e-9:
            break
        axes.append(ResponseAxis(
            index=k + 1,
            explained_share=round(eigenvalue / total_var, 4),
            loadings={c: round(vec[j], 4) for j, c in enumerate(codes)},
        ))
        for a in range(p):                                   # дефляция
            for b in range(p):
                cov[a][b] -= eigenvalue * vec[a] * vec[b]
    return axes
