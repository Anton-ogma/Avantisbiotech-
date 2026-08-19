"""DIERS formetric 4D, экспорт CSV из DICAM Software.

MUST §5.3: знаковые соглашения и единицы задаются ЗДЕСЬ и только здесь,
по версиям формата. Property-тест зеркальности (tests/test_sign_conventions.py)
написан до парсера — как требует ТЗ.
"""
from __future__ import annotations

from .base import ParseResult, parse_number, read_rows, register

#: Отображение заголовка DICAM → канонический код. ТОЧНОЕ соответствие, не
#: подстрочное: 'VP' как подстрока ловит 'VP_Max', 'Trunk_Imbalance_Lat_Dev'
#: попадает не туда, куда ожидается. Нераспознанные столбцы уходят в unmapped
#: и в raw_row, но не в параметры.
COLUMN_MAP: dict[str, str] = {
    "Trunk Imbalance VP-DM": "TRUNK_IMBALANCE_VP_DM",
    "Trunk_Imbalance_VP_DM": "TRUNK_IMBALANCE_VP_DM",
    "Rumpflaenge VP-DM": "TRUNK_IMBALANCE_VP_DM",
    "Sagittal Imbalance VP-DM": "SAGITTAL_IMBALANCE_VP_DM",
    "Sagittal_Imbalance_VP_DM": "SAGITTAL_IMBALANCE_VP_DM",
    "Lateral Deviation rms": "LATERAL_DEVIATION_RMS",
    "Lateral_Deviation_rms": "LATERAL_DEVIATION_RMS",
    "Seitabweichung rms": "LATERAL_DEVIATION_RMS",
    "Lateral Deviation max": "LATERAL_DEVIATION_MAX",
    "Lateral_Deviation_max": "LATERAL_DEVIATION_MAX",
    "Vertebral Rotation rms": "VERTEBRAL_ROTATION_RMS",
    "Vertebral_Rotation_rms": "VERTEBRAL_ROTATION_RMS",
    "Vertebral Rotation max": "VERTEBRAL_ROTATION_MAX",
    "Surface Rotation rms": "SURFACE_ROTATION_RMS",
    "Kyphotic Angle ICT-ITL": "KYPHOTIC_ANGLE_ICT_ITL",
    "Kyphotic_Angle_ICT_ITL": "KYPHOTIC_ANGLE_ICT_ITL",
    "Kyphosewinkel ICT-ITL": "KYPHOTIC_ANGLE_ICT_ITL",
    "Lordotic Angle ITL-ILS": "LORDOTIC_ANGLE_ITL_ILS",
    "Lordotic_Angle_ITL_ILS": "LORDOTIC_ANGLE_ITL_ILS",
    "Lordosewinkel ITL-ILS": "LORDOTIC_ANGLE_ITL_ILS",
    "Pelvic Obliquity DL-DR": "PELVIC_OBLIQUITY_DL_DR",
    "Pelvic_Obliquity_DL_DR": "PELVIC_OBLIQUITY_DL_DR",
    "Beckenschiefstand DL-DR": "PELVIC_OBLIQUITY_DL_DR",
    "Pelvic Torsion": "PELVIC_TORSION",
    "Pelvic Rotation": "PELVIC_ROTATION",
    "Pelvic Tilt": "PELVIC_TILT",
    "Trunk Inclination": "TRUNK_INCLINATION",
}

#: Знаковые соглашения по версиям формата (§5.3). Ключ — код параметра,
#: значение — множитель приведения к каноническому знаку.
#: Канон: положительное = отклонение вправо / вперёд / по часовой.
SIGN_CONVENTIONS: dict[str, dict[str, float]] = {
    "formetric-csv-v4": {
        "PELVIC_OBLIQUITY_DL_DR": -1.0,   # DICAM v4 считает влево положительным
        "PELVIC_ROTATION": -1.0,
        "VERTEBRAL_ROTATION_MAX": -1.0,
    },
    "formetric-csv-v3": {},
}

#: Параметры, для которых знак определён и подлежит зеркалированию в property-тесте.
SIGNED_PARAMS = frozenset({
    "TRUNK_IMBALANCE_VP_DM", "LATERAL_DEVIATION_MAX", "VERTEBRAL_ROTATION_MAX",
    "PELVIC_OBLIQUITY_DL_DR", "PELVIC_ROTATION", "PELVIC_TORSION",
})

MARKERS = ("Kyphotic Angle", "Kyphosewinkel", "Trunk Imbalance", "Rumpflaenge", "Lateral Deviation")


def apply_sign_conventions(params: dict[str, float], format_id: str) -> dict[str, float]:
    conv = SIGN_CONVENTIONS.get(format_id, {})
    return {code: value * conv.get(code, 1.0) for code, value in params.items()}


@register
class FormetricCsvParser:
    format_id = "formetric-csv-v4"
    modality = "formetric"

    def detect(self, blob: bytes) -> bool:
        try:
            headers, _ = read_rows(blob)
        except Exception:
            return False
        joined = " ".join(headers)
        return any(m in joined for m in MARKERS)

    def parse(self, blob: bytes) -> list[ParseResult]:
        _headers, rows = read_rows(blob)
        out: list[ParseResult] = []
        for row in rows:
            params: dict[str, float] = {}
            unmapped: dict[str, str] = {}
            flags: list[str] = []
            for header, raw in row.items():
                code = COLUMN_MAP.get(header)
                if code is None:
                    if raw:
                        unmapped[header] = raw
                    continue
                value = parse_number(raw)
                if value is None:
                    flags.append(f"missing_landmark:{code}")
                    continue
                params[code] = value
            if not params:
                # Ни один канонический столбец не распознан. НЕ пишем сырую строку
                # в параметры (это дефект Д-09 унаследованного модуля) — помечаем.
                flags.append("no_canonical_columns")
            out.append(ParseResult(
                format_id=self.format_id,
                modality=self.modality,
                device_sw_version=row.get("SW Version") or row.get("Version"),
                params=apply_sign_conventions(params, self.format_id),
                unmapped=unmapped,
                quality_flags=flags,
                raw_row=dict(row),
            ))
        return out
