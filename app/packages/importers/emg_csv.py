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
from typing import TYPE_CHECKING

if TYPE_CHECKING:                       # только для подсказки типа
    from domain.montage import ChannelMap

from typing import ClassVar

from domain.config import load_muscles

from .base import ParseResult, parse_number, read_rows, register

SIDE_ALIASES: dict[str, str] = {
    "l": "L", "left": "L", "лев": "L", "слева": "L", "л": "L",
    "r": "R", "right": "R", "прав": "R", "справа": "R", "п": "R",
}

CONDITION_KEYS = ("Condition", "Probe", "Проба", "Условие", "Test")
MARKERS = ("RMS", "µV", "uV", "мкВ", "EMG", "ЭМГ")


def resolve_channel(label: str, montage: ChannelMap | None = None) -> tuple[str, str] | None:
    """«MASS_L», «Masseter left», «жев слева» → ('MASSETER', 'L').

    Каталог мышц — единственный словарь (Р-42): раньше алиасы жили здесь
    отдельным dict и расходились с реестром при каждом пополнении.

    `montage` — ручная пропись каналов сессии. Она проверяется ПЕРВОЙ и
    решает случай, ради которого затевалась: миограф подписывает провода
    «CH1…CH8», и по имени столбца мышцу не восстановить никак. Догадываться
    платформа не имеет права — либо метка узнаётся, либо канал прописан.
    """
    if montage:
        direct = montage.get(label.strip().lower())
        if direct is not None:
            return direct
    catalog = load_muscles()
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
    if side is None:
        return None
    muscle = catalog.by_alias(" ".join(parts)) or catalog.by_alias(parts[0])
    if muscle is None or not muscle.surface:
        return None
    return muscle.code, side


@register
class EmgCsvParser:
    format_id = "emg-csv-v1"
    modality = "emg"

    def detect(self, blob: bytes, montage: ChannelMap | None = None) -> bool:
        """Признак формата — РАСПОЗНАННЫЕ КАНАЛЫ, а не слово RMS в заголовке.

        Слово «rms» встречается и в формометрии («Lateral Deviation rms»),
        поэтому маркер сам по себе перехватывал чужой файл. Канал же требует
        и мышцу, и сторону одновременно — совпасть случайно почти невозможно.

        `montage` передаётся только на ВТОРОМ заходе, когда файл не опознал
        никто (Р-42). Иначе прописанные метки вроде «CH1» перетягивали бы на
        себя посторонние таблицы: две колонки с такими именами есть где угодно.
        """
        try:
            headers, rows = read_rows(blob)
        except Exception:
            return False
        if sum(1 for h in headers if resolve_channel(h, montage)) >= 2:
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

    def parse(self, blob: bytes, montage: ChannelMap | None = None) -> list[ParseResult]:
        headers, rows = read_rows(blob)
        long_form = any(h.lower() in ("muscle", "мышца", "channel", "канал") for h in headers)
        if long_form:
            return [self._long(rows, montage)]
        return [self._wide(row, montage) for row in rows]

    def _wide(self, row: dict[str, str], montage: ChannelMap | None = None) -> ParseResult:
        params: dict[str, float] = {}
        unmapped: dict[str, str] = {}
        for header, raw in row.items():
            resolved = resolve_channel(header, montage)
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

    def _long(self, rows: list[dict[str, str]],
              montage: ChannelMap | None = None) -> ParseResult:
        params: dict[str, float] = {}
        unmapped: dict[str, str] = {}
        condition = ""
        for row in rows:
            muscle_raw = next(
                (row[k] for k in ("Muscle", "Мышца", "Channel", "Канал") if row.get(k)), "")
            side_raw = next((row[k] for k in ("Side", "Сторона") if row.get(k)), "")
            value = next((parse_number(row[k]) for k in ("RMS", "RMS_uV", "Value", "Значение")
                          if row.get(k)), None)
            condition = condition or next((row[k] for k in CONDITION_KEYS if row.get(k)), "")
            resolved = resolve_channel(f"{muscle_raw} {side_raw}", montage)
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
            left = params.get(f"EMG_RMS_{muscle}_L")
            right = params.get(f"EMG_RMS_{muscle}_R")
            if left is not None and right is not None and (abs(left) + abs(right)) > 0:
                params[f"EMG_ASYM_{muscle}"] = round(
                    200 * (right - left) / (abs(right) + abs(left)), 2)

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

    Р-41: сила измеряется ПОД ПРОБОЙ, как формометрия, ЭМГ и кондилография.
    Прежняя редакция §9.8 считала её сессионной характеристикой — это неверно
    для протокола, где одноимённые пробы ставятся на всех четырёх приборах:
    одно число на сессию стирало бы ровно тот эффект, ради которого измерение
    и делается.

    Файл БЕЗ метки условия по-прежнему принимается как сессионный: у клиники
    остаются архивные выгрузки, и отвергать их из-за отсутствия столбца нельзя.
    Различаются они флагом качества, а не молча.
    """

    format_id = "myoline-csv-v1"
    modality = "myoline"

    GROUP_ALIASES: ClassVar[dict[str, str]] = {
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
        # Строки группируются по условию: одна выгрузка обычно несёт все пробы
        # подряд, и разрезать её на файлы вручную оператор не должен.
        by_condition: dict[str, dict[str, float]] = {}
        unmapped: dict[str, str] = {}
        for row in rows:
            condition = next((row[k] for k in CONDITION_KEYS if row.get(k)), "").strip()
            group_raw = next((row[k] for k in ("Group", "Movement", "Группа", "Движение")
                              if row.get(k)), "")
            value = next((parse_number(row[k]) for k in ("Force_N", "Force", "Сила", "N")
                          if row.get(k)), None)
            code = self.GROUP_ALIASES.get(group_raw.strip().lower().replace(" ", "_"))
            if code is None or value is None:
                if group_raw:
                    unmapped[group_raw] = str(value)
                continue
            by_condition.setdefault(condition, {})[f"MYO_FORCE_{code}"] = value

        out: list[ParseResult] = []
        for condition, params in by_condition.items():
            add_lateral_asymmetry(params)
            flags: list[str] = []
            if not params:
                flags.append("no_canonical_columns")
            elif not condition:
                # Без метки условия сила не привязывается к пробе и остаётся
                # сессионной ковариатой. Это ограничение файла, а не методики.
                flags.append("myoline_session_level_no_condition")
            out.append(ParseResult(
                format_id=self.format_id, modality=self.modality, device_sw_version=None,
                params=params, unmapped=unmapped, quality_flags=flags,
                raw_row={"condition_label": condition},
            ))
        return out or [ParseResult(
            format_id=self.format_id, modality=self.modality, device_sw_version=None,
            params={}, unmapped=unmapped, quality_flags=["no_canonical_columns"], raw_row={},
        )]


def add_lateral_asymmetry(params: dict[str, float]) -> None:
    """MYO_ASYM_TRUNK_LAT — асимметрия боковой силы, в процентах.

    Считается так же, как асимметрия ЭМГ и мыщелков: 200·(R−L)/(|R|+|L|).
    Единая формула важнее удобства — иначе три «асимметрии» в одном отчёте
    оказались бы величинами с разной шкалой под одним словом.
    """
    right = params.get("MYO_FORCE_TRUNK_LAT_R")
    left = params.get("MYO_FORCE_TRUNK_LAT_L")
    if right is None or left is None or (abs(right) + abs(left)) == 0:
        return
    params["MYO_ASYM_TRUNK_LAT"] = round(
        200 * (right - left) / (abs(right) + abs(left)), 2)
