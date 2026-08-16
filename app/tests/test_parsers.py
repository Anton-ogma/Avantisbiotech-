"""Фикстуры парсеров: реальный файл каждого формата → ожидаемый разбор (§16)."""
from pathlib import Path

import pytest
from importers import ParserNotFound, detect_parser, parse_blob
from importers.base import parse_number

FIXTURES = Path(__file__).parent / "fixtures"


def test_formetric_csv_fixture():
    parser, results = parse_blob((FIXTURES / "formetric_dicam_v4.csv").read_bytes())
    assert parser.format_id == "formetric-csv-v4"
    assert len(results) == 2
    first = results[0]
    assert first.params["KYPHOTIC_ANGLE_ICT_ITL"] == 45.1
    assert first.params["TRUNK_IMBALANCE_VP_DM"] == 8.4
    # Знаковое соглашение DICAM v4 применено
    assert first.params["PELVIC_OBLIQUITY_DL_DR"] == -3.2
    # Нераспознанные столбцы НЕ теряются и НЕ попадают в параметры (в отличие
    # от дефекта Д-09 унаследованного модуля)
    assert "Patient ID" in first.unmapped
    assert "Patient ID" not in first.params


@pytest.mark.parametrize(
    "raw,expected",
    [("12,5", 12.5), ("12.5", 12.5), ("1,234.5", 1234.5), ("-3,2", -3.2), ("", None), ("н/д", None)],
)
def test_decimal_separator_from_content_not_locale(raw, expected):
    """MUST §5.2: разделитель определяется по содержимому значения."""
    assert parse_number(raw) == expected


def test_unrecognized_is_not_silently_skipped():
    """MUST §5.1: молчаливый пропуск запрещён."""
    with pytest.raises(ParserNotFound):
        detect_parser(b"Foo;Bar\n1;2\n")
