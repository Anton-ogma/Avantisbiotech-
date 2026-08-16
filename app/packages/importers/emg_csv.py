"""Поверхностная ЭМГ — CSV выгрузки миографа.

Поддерживаются обе раскладки, встречающиеся у вендоров:
  • широкая: одна строка на пробу, столбцы «MASS_L;MASS_R;TEMP_L;…»;
  • длинная: строка на канал, столбцы «Muscle;Side;RMS».

MUST §9.8: амплитуды в мкВ сравнимы ТОЛЬКО внутри одной сессии — между
сессиями электроды переклеиваются. Парсер помечает это флагом, а межсессионную
динамику ЭМГ платформа не строит без нормализации.
"""
from __future__ import annotations

import re

from .base import ParseResult, parse_number, read_rows, register

#: Сокращение вендора → канонический код мышцы. Словарь клиники, не догадка.
MUSCLE_ALIASES: dict[str, str] = {
    "mass": "MASSETER", "masseter": "MASSETER", "жев": "MASSETER", "жевательная": "MASSETER",
    "temp": "TEMPORALIS", "temporalis": "TEMPORALIS", "вис": "TEMPORALIS", "височная": "TEMPORALIS",
    "scm": "SCM", "гкс": "SCM",
    "trap": "TRAPEZIUS", "trapezius": "TRAPEZIUS", "трап": "TRAPEZIUS",
    "es": "ERECTOR_SPINAE", "erector": "ERECTOR_SPINAE", "erector spinae": "ERECTOR_SPINAE",
    "ql": "QUADRATUS_LUMBORUM", "quadratus": "QUADRATUS_LUMBORUM",
    "gm": "GLUTEUS_MAXIMUS", "gluteus": "GLUTEUS_MAXIMUS",
    "rf": "RECTUS_FEMORIS", "rectus femoris": "RECTUS_FEMORIS",
    "ta": "TIBIALIS_ANTERIOR", "tibialis": "TIBIALIS_ANTERIOR",
    "gs": "GASTROCNEMIUS", "gastro": "GASTROCNEMIUS", "gastrocnemius": "GASTROCNEMIUS",
}
SIDE_ALIASES: dict[str, str] = {
    "l": "L", "left": "L", "лев": "L", "слева": "L", "л": "L",
    "r": "R", "right": "R", "прав": "R", "справа": "R", "п": "R",
}

CONDITION_KEYS = ("Condition", "Probe", "Проба", "Условие", "Test")
MARKERS = ("RMS", "µV", "uV", "мкВ", "EMG", "ЭМГ")


def resolve_channel(label: str) -> tuple[str, str] | None:
    """«MASS_L», «Masseter left», «жев слева» → ('MASSETER', 'L')."""
    text = label.strip().lower().replace("-", "_")
    text = re.sub(r"\b(rms|emg|эмг|мкв|uv|µv)\b", " ", text)
    parts = [p for p in re.split(r"[\s_;,]+", text) if p]
    if not parts:
        return None
    side = None
    for p in reversed(parts):
        if p in SIDE_ALIASES:
            side = SIDE_ALIASES[p]
            parts.remove(p)
            break
    stem = " ".join(parts).strip()
    muscle = MUSCLE_ALIASES.get(stem) or MUSCLE_ALIASES.get(parts[0] if parts else "")
    if muscle is None or side is None:
        return None
    return muscle, side


@register
class EmgCsvParser:
    format_id = "emg-csv-v1"
    modality = "emg"

    def detect(self, blob: bytes) -> bool:
        """Признак формата — РАСПОЗНАННЫЕ КАНАЛЫ, а не слово RMS в заголовке.

        Слово «rms» встречается и в формометрии («Lateral Deviation rms»),
        поэтому маркер сам по себе перехватывал чужой файл. Канал же требует
        и мышцу, и сторону одновременно — совпасть случайно почти невозможно.
        """
        try:
            headers, rows = read_rows(blob)
        except Exception:
            return False
        if sum(1 for h in headers if resolve_channel(h)) >= 2:
            return True
        # длинная раскладка: столбцы «Мышца / Сторона / RMS»
        lowered = {h.strip().lower() for h in headers}
        if not lowered & {"muscle", "мышца", "channel", "канал"}:
            return False
        if not lowered & {"rms", "rms_uv", "value", "значение"}:
            return False
        return any(
            resolve_channel(f"{row.get('Muscle', row.get('Мышца', ''))} "
                            f"{row.get('Side', row.get('Сторона', ''))}")
            for row in rows[:5]
        )

    def parse(self, blob: bytes) -> list[ParseResult]:
        headers, rows = read_rows(blob)
        long_form = any(h.lower() in ("muscle", "мышца", "channel", "канал") for h in headers)
        return [self._long(rows)] if long_form else [self._wide(row) for row in rows]

    def _wide(self, row: dict[str, str]) -> ParseResult:
        params: dict[str, float] = {}
        unmapped: dict[str, str] = {}
        for header, raw in row.items():
            resolved = resolve_channel(header)
            if resolved is None:
                if raw:
                    unmapped[header] = raw
                continue
            value = parse_number(raw)
            if value is None:
                continue
            muscle, side = resolved
            params[f"EMG_RMS_{muscle}_{side}"] = value
        condition = next((row[k] for k in CONDITION_KEYS if row.get(k)), "")
        return self._finish(params, unmapped, condition, row)

    def _long(self, rows: list[dict[str, str]]) -> ParseResult:
        params: dict[str, float] = {}
        unmapped: dict[str, str] = {}
        condition = ""
        for row in rows:
            muscle_raw = next((row[k] for k in ("Muscle", "Мышца", "Channel", "Канал") if row.get(k)), "")
            side_raw = next((row[k] for k in ("Side", "Сторона") if row.get(k)), "")
            value = next((parse_number(row[k]) for k in ("RMS", "RMS_uV", "Value", "Значение")
                          if row.get(k)), None)
            condition = condition or next((row[k] for k in CONDITION_KEYS if row.get(k)), "")
            resolved = resolve_channel(f"{muscle_raw} {side_raw}")
            if resolved is None or value is None:
                if muscle_raw:
                    unmapped[muscle_raw] = side_raw
                continue
            muscle, side = resolved
            params[f"EMG_RMS_{muscle}_{side}"] = value
        return self._finish(params, unmapped, condition, {})

    @staticmethod
    def _finish(params: dict[str, float], unmapped: dict[str, str],
                condition: str, raw: dict[str, str]) -> ParseResult:
        # Асимметрия каналов — величина, ради которой ЭМГ здесь и нужна.
        for muscle in {c[len("EMG_RMS_"):-2] for c in params if c.startswith("EMG_RMS_")}:
            l, r = params.get(f"EMG_RMS_{muscle}_L"), params.get(f"EMG_RMS_{muscle}_R")
            if l is not None and r is not None and (abs(l) + abs(r)) > 0:
                params[f"EMG_ASYM_{muscle}"] = round(200 * (r - l) / (abs(r) + abs(l)), 2)

        flags = ["emg_amplitude_session_scoped"]      # MUST §9.8, не декоративный флаг
        if not params:
            flags.append("no_canonical_columns")
        low = [c for c, v in params.items() if c.startswith("EMG_RMS_") and v <= 0.5]
        if low:
            flags.append(f"low_snr:{len(low)}ch")     # канал у нуля не интерпретируется

        return ParseResult(
            format_id="emg-csv-v1", modality="emg", device_sw_version=None,
            params=params, unmapped=unmapped, quality_flags=flags,
            raw_row={**raw, "condition_label": condition},
        )


@register
class MyolineCsvParser:
    """DIERS Myoline — изометрическая сила.

    MUST §9.8: в анализе проб не участвует. Ковариата для дозирования программы
    и для гипотезы «сильные отвечают иначе» (Р-35, слой 3).
    """

    format_id = "myoline-csv-v1"
    modality = "myoline"

    GROUP_ALIASES = {
        "trunk_ext": "TRUNK_EXT", "extension": "TRUNK_EXT", "разгибание": "TRUNK_EXT",
        "trunk_flex": "TRUNK_FLEX", "flexion": "TRUNK_FLEX", "сгибание": "TRUNK_FLEX",
        "lat_left": "TRUNK_LAT_L", "наклон_влево": "TRUNK_LAT_L",
        "lat_right": "TRUNK_LAT_R", "наклон_вправо": "TRUNK_LAT_R",
    }

    def detect(self, blob: bytes) -> bool:
        try:
            headers, _ = read_rows(blob)
        except Exception:
            return False
        joined = " ".join(headers).lower()
        return ("myoline" in joined or "force" in joined or "сила" in joined) and (
            "n" in [h.strip().lower() for h in headers] or "force_n" in joined or "сила" in joined
        )

    def parse(self, blob: bytes) -> list[ParseResult]:
        _, rows = read_rows(blob)
        params: dict[str, float] = {}
        unmapped: dict[str, str] = {}
        for row in rows:
            group_raw = next((row[k] for k in ("Group", "Movement", "Группа", "Движение")
                              if row.get(k)), "")
            value = next((parse_number(row[k]) for k in ("Force_N", "Force", "Сила", "N")
                          if row.get(k)), None)
            code = self.GROUP_ALIASES.get(group_raw.strip().lower().replace(" ", "_"))
            if code is None or value is None:
                if group_raw:
                    unmapped[group_raw] = str(value)
                continue
            params[f"MYO_FORCE_{code}"] = value
        return [ParseResult(
            format_id=self.format_id, modality=self.modality, device_sw_version=None,
            params=params, unmapped=unmapped,
            quality_flags=["myoline_not_in_probe_analysis"] if params else ["no_canonical_columns"],
            raw_row={},
        )]
