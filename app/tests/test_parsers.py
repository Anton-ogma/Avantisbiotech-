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


# ── Реальные протоколы приборов клиники (§5.2 MUST: файл на каждый парсер) ────

def test_formetric_dynamic4d_protocol():
    """DIERS formetric 4D, Parameter_F4_Dynamic4D, условие «лев окк», 3 км/ч."""
    parser, results = parse_blob((FIXTURES / "formetric_dynamic4d_protocol.txt").read_bytes())
    assert parser.format_id == "formetric-pdf-protocol-v1"
    r = results[0]
    assert r.raw_row["condition_label"] == "лев окк"
    assert r.raw_row["date"] == "04.03.2025"
    assert r.params["GAIT_SPEED_KMH"] == 3.0
    assert r.params["DYN_KYPHOTIC_ANGLE_ICT_ITL_MAX"] == 38.0
    assert r.params["DYN_SAGITTAL_IMBALANCE_VP_DM"] == 5.0      # градусы, не мм


def test_side_word_becomes_canonical_sign():
    """Прибор печатает модуль и сторону словом; канон — вправо положительно (§5.3)."""
    _, results = parse_blob((FIXTURES / "formetric_dynamic4d_protocol.txt").read_bytes())
    p = results[0].params
    assert p["DYN_PELVIC_OBLIQUITY"] == 17.0                    # «17 мм Прав.» → +17
    assert p["DYN_PELVIC_ROTATION_ROM_MIN"] == -1.0             # «1° Лев.»     → −1


def test_range_bounds_are_sorted_not_taken_in_print_order():
    """Ловушка настоящего протокола: «20 мм Прав. - 6 мм Прав.» — границы идут
    в порядке фазы цикла. Наивное «первое = минимум» даёт размах −14."""
    from importers.formetric_pdf import parse_range

    assert parse_range("20 мм Прав. - 6 мм Прав.") == (6.0, 20.0)
    assert parse_range("1° Лев. - 7° Прав.") == (-1.0, 7.0)

    _, results = parse_blob((FIXTURES / "formetric_dynamic4d_protocol.txt").read_bytes())
    p = results[0].params
    assert p["DYN_PELVIC_OBLIQUITY_ROM"] == 14.0               # 20 − 6, а не 6 − 20
    assert p["DYN_PELVIC_ROTATION_ROM"] == 8.0                 # +7 − (−1)
    assert all(v >= 0 for k, v in p.items() if k.endswith("_ROM"))


def test_cadiax_open_close():
    """CADIAX 4, числовой анализ, движение «Открывание/закрывание»."""
    parser, results = parse_blob((FIXTURES / "cadiax_open_close.txt").read_bytes())
    assert parser.format_id == "cadiax-numeric-v4"
    r = results[0]
    assert r.raw_row["movement_code"] == "CDG_OPEN_CLOSE"
    assert r.params["CDG_MAX_EXCURSION_R"] == 22.45
    assert r.params["CDG_MAX_EXCURSION_L"] == 20.82
    assert r.params["CDG_SCI_10MM_R"] == 51.93
    assert r.params["CDG_TCI_3MM_L"] == -6.42                   # минус U+2212
    assert r.params["CDG_QUANTITY_SYMMETRY"] == 107.85
    assert r.params["CDG_MAX_ROTATION_GAMMA"] == 29.90


def test_cadiax_flags_uneven_reproducibility():
    """Собственная метрология прибора: 0,46 справа против 0,03 слева — признак
    неравного качества записи, а не биологической асимметрии."""
    _, results = parse_blob((FIXTURES / "cadiax_open_close.txt").read_bytes())
    assert "reproducibility_side_mismatch:3mm" in results[0].quality_flags

    _, clean = parse_blob((FIXTURES / "cadiax_protrusion_retrusion.txt").read_bytes())
    assert not any(f.startswith("reproducibility") for f in clean[0].quality_flags)


def test_clinic_label_resolves_to_probe_code(bundle):
    """Метка условия из протокола разрешается реестром, а не догадкой парсера."""
    assert bundle.probes.by_alias("лев окк").code == "MAND_OCCLUSION_LEFT"
    assert bundle.probes.by_alias("открывание/закрывание").code == "CDG_OPEN_CLOSE"
    assert bundle.probes.by_alias("неизвестное условие") is None


def test_occlusion_is_not_equated_with_laterotrusion(bundle):
    """Р-36: «лев окк» и латеротрузия влево — РАЗНЫЕ коды. Отождествить их
    значило бы предрешить результат исследования."""
    assert bundle.probes.get("MAND_OCCLUSION_LEFT") is not None
    assert bundle.probes.get("MAND_LAT_LEFT") is not None
    assert bundle.probes.by_alias("лев окк").code != "MAND_LAT_LEFT"


def test_excursion_cross_check_blocks_link_on_mismatch():
    """§6.2: расхождение экскурсии выше допуска — связка по коду пробы не строится."""
    from domain.effects import match_excursion

    assert match_excursion(22.0, 22.45).status == "matched"
    assert match_excursion(18.0, 22.45).status == "mismatch"
    assert match_excursion(None, 22.45).status == "absent"


def test_emg_detector_does_not_hijack_formetric():
    """Регрессия: заголовок формометрии содержит «Lateral Deviation rms», и маркер
    RMS сам по себе перехватывал чужой формат. Признак — распознанные каналы."""
    parser, _ = parse_blob((FIXTURES / "formetric_dicam_v4.csv").read_bytes())
    assert parser.format_id == "formetric-csv-v4"


def test_emg_wide_and_long_layouts():
    parser, results = parse_blob((FIXTURES / "emg_wide.csv").read_bytes())
    assert parser.format_id == "emg-csv-v1"
    assert len(results) == 2                       # строка на условие
    first = results[0]
    assert first.raw_row["condition_label"] == "лев окк"
    assert first.params["EMG_RMS_MASSETER_R"] == 51.7
    assert first.params["EMG_ASYM_MASSETER"] == 30.03
    # MUST §9.8: мкВ сравнимы только внутри сессии — флаг не декоративный
    assert "emg_amplitude_session_scoped" in first.quality_flags

    _, long_form = parse_blob((FIXTURES / "emg_long.csv").read_bytes())
    assert long_form[0].params["EMG_RMS_TEMPORALIS_R"] == 20.4


def test_myoline_excluded_from_probe_analysis():
    """MUST §9.8: изометрическая сила в анализе проб не участвует."""
    parser, results = parse_blob((FIXTURES / "myoline_force.csv").read_bytes())
    assert parser.format_id == "myoline-csv-v1"
    assert results[0].params["MYO_FORCE_TRUNK_EXT"] == 412.5
    assert "myoline_not_in_probe_analysis" in results[0].quality_flags


def test_channel_resolution_needs_muscle_and_side():
    from importers.emg_csv import resolve_channel

    assert resolve_channel("MASS_L") == ("MASSETER", "L")
    assert resolve_channel("Masseter right") == ("MASSETER", "R")
    assert resolve_channel("жев слева") == ("MASSETER", "L")
    assert resolve_channel("Masseter") is None          # без стороны — не канал
    assert resolve_channel("Lateral Deviation rms") is None
