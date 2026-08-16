"""Property-тест знаковых соглашений (§5.3 ТЗ).

MUST: этот тест пишется ДО первого парсера. Зеркальный набор входных данных
даёт зеркальный результат по всем знаковым параметрам.
"""
from importers.formetric_csv import SIGNED_PARAMS, apply_sign_conventions


def _mirror_csv(rows: list[dict[str, str]]) -> bytes:
    header = ";".join(rows[0])
    lines = [header]
    for row in rows:
        lines.append(";".join(row[k] for k in rows[0]))
    return "\r\n".join(lines).encode("utf-8")


def test_sign_conventions_are_involutive():
    """Двойное применение соглашения возвращает исходное значение."""
    values = {code: 3.5 for code in SIGNED_PARAMS}
    once = apply_sign_conventions(values, "formetric-csv-v4")
    twice = apply_sign_conventions(once, "formetric-csv-v4")
    assert twice == values


def test_mirrored_input_gives_mirrored_output():
    """Зеркальный вход → зеркальный выход по всем знаковым параметрам."""
    values = {"PELVIC_OBLIQUITY_DL_DR": 3.2, "PELVIC_ROTATION": -1.4, "TRUNK_IMBALANCE_VP_DM": 8.4}
    mirrored = {k: -v for k, v in values.items()}
    a = apply_sign_conventions(values, "formetric-csv-v4")
    b = apply_sign_conventions(mirrored, "formetric-csv-v4")
    assert b == {k: -v for k, v in a.items()}


def test_unsigned_params_untouched():
    values = {"KYPHOTIC_ANGLE_ICT_ITL": 45.0, "LATERAL_DEVIATION_RMS": 6.0}
    assert apply_sign_conventions(values, "formetric-csv-v4") == values
