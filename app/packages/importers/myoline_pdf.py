"""DIERS myoline — печатный отчёт «Comparison Agonist/Antagonist» (PDF), Р-48.

Формат отличается от CSV-выгрузки принципиально: это не таблица сил, а
сопоставление агониста с антагонистом по областям тела. На листе девять пар
движений — туловище, шея, ноги, предплечье, плечо, — и к каждой паре прибор
печатает пиктограмму работающей мышцы.

ТРИ ВЕЩИ, КОТОРЫЕ ЗДЕСЬ ДЕЛАЮТСЯ ЯВНО.

1. **Пара называет свои движения сама.** Строка «Туловище| Разгибание /
   Сгибание» задаёт область и порядок, а следующие строки дают значения по
   имени движения. Привязка идёт по имени, а не по порядку следования: сбой
   порядка при другой версии печати иначе переставил бы стороны местами, и
   левое стало бы правым — ошибка, неотличимая от биологии.

2. **Процент — это норматив ПРИБОРА, а не наша норма.** «252 N / 78%» означает
   78 % от норматива DIERS. Платформа работает без норм (Р-13), и подставить
   чужой норматив на их место нельзя: тогда «отклонение от нормы» считалось бы
   по шкале, которую мы не проверяли. Проценты сохраняются отдельными кодами
   `MYO_PCT_*` и в индексы не входят.

3. **ФИО со страницы НЕ сохраняется.** Отчёт печатает имя и дату рождения;
   ПДн внутрь модуля не попадают (Р-9, ФЗ-152). Строки с именем отбрасываются
   до того, как что-либо попадёт в `unmapped`, — иначе они осели бы там под
   видом «неканонического столбца».
"""
from __future__ import annotations

import re

from .base import Figure, ParseResult, register

#: Русское название движения → суффикс кода. Пары печатаются как «А / Б»,
#: и каждое движение опознаётся по своему имени.
MOVEMENTS: dict[str, str] = {
    "разгибание": "EXT",
    "сгибание": "FLEX",
    "наклон налево": "LAT_L",
    "наклон влево": "LAT_L",
    "наклон направо": "LAT_R",
    "наклон вправо": "LAT_R",
    "ротация влево": "ROT_L",
    "ротация вправо": "ROT_R",
    "отведение": "ABD",
    "приведение": "ADD",
    "разгибание локтя": "ELBOW_EXT",
    "сгибание локтя": "ELBOW_FLEX",
    "ротация наружу": "ROT_EXT",
    "ротация внутрь": "ROT_INT",
}

#: Область на листе → часть кода. Порядок важен для сопоставления с реестром.
REGIONS: dict[str, str] = {
    "туловище": "TRUNK",
    "шейный отдел": "CERVICAL",
    "ноги": "LEG",
    "предплечье": "FOREARM",
    "плечо": "SHOULDER",
}

#: Строки, которые не должны попасть даже в `unmapped`: ПДн и реквизиты клиники.
_DROP = re.compile(r"^\s*(имя|name|patient|пациент)\s*[:：]", re.IGNORECASE)
_ORG = re.compile(r"(https?://|\+7\s*\(|ул\.|проспект|центр\s)", re.IGNORECASE)

_PAIR = re.compile(r"^(?P<region>[^|]+)\|\s*(?P<a>[^/]+)/\s*(?P<b>.+)$")
_VALUE = re.compile(r"^(?P<name>[А-Яа-яЁё\s]+?)\s+(?P<force>-?\d+(?:[.,]\d+)?)\s*N\s*/\s*"
                    r"(?P<pct>\d+(?:[.,]\d+)?)\s*%")
# MULTILINE обязателен: строка последовательности стоит в середине листа, и без
# него «$» означал бы конец документа — метка условия молча терялась бы.
_SEQUENCE = re.compile(r"последовательность\s+Из\s+(\d{2}\.\d{2}\.\d{4})\s*\|\s*(.+?)$",
                       re.IGNORECASE | re.MULTILINE)
_VERSION = re.compile(r"Версия ПО\s*([\d.]+)")

#: Пиктограмма работающей мышцы: у настоящего отчёта это квадрат ~129 px.
#: Полоски в один пиксель — оформление шкалы, содержания не несут.
_MIN_SIDE = 60


def code_for(region: str, movement: str) -> str | None:
    """(«Туловище», «Наклон налево») → MYO_FORCE_TRUNK_LAT_L."""
    r = REGIONS.get(region.strip().lower())
    m = MOVEMENTS.get(movement.strip().lower())
    return f"MYO_FORCE_{r}_{m}" if r and m else None


@register
class MyolinePdfParser:
    format_id = "myoline-pdf-agonist-v1"
    modality = "myoline"

    def detect(self, blob: bytes) -> bool:
        if not blob.startswith(b"%PDF"):
            return False
        text = _text(blob)
        if "Comparison Agonist/Antagonist" in text:
            return True
        # Запасной признак: нормативная шкала и хотя бы одна пара «сила / процент».
        return "норматив" in text.lower() and bool(_VALUE.search(text))

    def parse(self, blob: bytes) -> list[ParseResult]:
        text = _text(blob)
        params: dict[str, float] = {}
        unmapped: dict[str, str] = {}
        flags: list[str] = []
        region = ""
        pending: dict[str, str] = {}          # имя движения → область

        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or _DROP.search(line) or _ORG.search(line):
                continue                       # ПДн и реквизиты клиники не хранятся
            pair = _PAIR.match(line)
            if pair and pair.group("region").strip().lower() in REGIONS:
                region = pair.group("region").strip()
                pending = {pair.group("a").strip().lower(): region,
                           pair.group("b").strip().lower(): region}
                continue
            value = _VALUE.match(line)
            if value is None:
                continue
            name = value.group("name").strip().lower()
            owner = pending.get(name, region)
            code = code_for(owner, name)
            if code is None:
                # Движение или область незнакомы. Молча терять нельзя (§5.1),
                # но и догадываться о коде — тем более: строка уходит в unmapped.
                unmapped[f"{owner}|{name}"] = line
                continue
            params[code] = float(value.group("force").replace(",", "."))
            params[code.replace("MYO_FORCE_", "MYO_PCT_")] = float(
                value.group("pct").replace(",", "."))

        _add_asymmetries(params)
        _add_agonist_ratios(params)

        if not params:
            flags.append("no_canonical_columns")
        else:
            # MUST: процент на листе — норматив ПРИБОРА. Наши нормы пусты (Р-13),
            # и подменять их чужой шкалой нельзя.
            flags.append("device_normative_percent_not_platform_norms")

        sequence = _SEQUENCE.search(text)
        version = _VERSION.search(text)
        figures = _figures(blob)
        return [ParseResult(
            format_id=self.format_id,
            modality=self.modality,
            device_sw_version=version.group(1) if version else None,
            params=params,
            unmapped=unmapped,
            quality_flags=flags,
            raw_row={
                "condition_label": sequence.group(2).strip() if sequence else "",
                "date": sequence.group(1) if sequence else "",
            },
            figures=figures,
        )]


def _add_asymmetries(params: dict[str, float]) -> None:
    """Асимметрия по парам L/R — та же формула, что у ЭМГ, силы и мыщелков."""
    bases = {c[:-2] for c in params
             if c.startswith("MYO_FORCE_") and c.endswith(("_L", "_R"))}
    for base in bases:
        r, l = params.get(f"{base}_R"), params.get(f"{base}_L")
        if r is None or l is None or (abs(r) + abs(l)) == 0:
            continue
        params[base.replace("MYO_FORCE_", "MYO_ASYM_")] = round(
            200 * (r - l) / (abs(r) + abs(l)), 2)


#: Пары агонист/антагонист, ради которых лист и печатается.
_RATIO_PAIRS = (
    ("TRUNK_EXT", "TRUNK_FLEX", "MYO_RATIO_TRUNK_EXT_FLEX"),
    ("CERVICAL_EXT", "CERVICAL_FLEX", "MYO_RATIO_CERVICAL_EXT_FLEX"),
    ("LEG_EXT", "LEG_FLEX", "MYO_RATIO_LEG_EXT_FLEX"),
    ("LEG_ABD", "LEG_ADD", "MYO_RATIO_LEG_ABD_ADD"),
    ("FOREARM_ELBOW_EXT", "FOREARM_ELBOW_FLEX", "MYO_RATIO_FOREARM_EXT_FLEX"),
    ("SHOULDER_ROT_EXT", "SHOULDER_ROT_INT", "MYO_RATIO_SHOULDER_EXT_INT"),
)


def _add_agonist_ratios(params: dict[str, float]) -> None:
    """Отношение агониста к антагонисту — то, что лист и называет своим именем.

    Считается отношением сил, а не процентов: проценты нормированы на чужой
    норматив, и их отношение измеряло бы шкалу прибора, а не пациента.
    """
    for agonist, antagonist, code in _RATIO_PAIRS:
        a = params.get(f"MYO_FORCE_{agonist}")
        b = params.get(f"MYO_FORCE_{antagonist}")
        if a is None or b is None or b == 0:
            continue
        params[code] = round(a / b, 3)


def _text(blob: bytes) -> str:
    import io

    from pypdf import PdfReader

    return "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(blob)).pages)


def _figures(blob: bytes) -> list[Figure]:
    """Пиктограммы работающих мышц. Структура — «сила»: лист об этом и говорит."""
    import io

    from pypdf import PdfReader

    out: list[Figure] = []
    for index, page in enumerate(PdfReader(io.BytesIO(blob)).pages):
        try:
            images = list(page.images)
        except Exception:                                  # pragma: no cover
            continue
        for im in images:
            try:
                data, w, h = im.data, im.image.width, im.image.height
            except Exception:                              # pragma: no cover
                continue
            if w < _MIN_SIDE or h < _MIN_SIDE:
                continue                # полоски шкалы и логотипы — оформление
            mime = "image/png" if data[:4] == b"\x89PNG" else "image/jpeg"
            out.append(Figure(name=im.name, mime=mime, width=w, height=h,
                              kind="render", data=data,
                              structures=("strength",), page=index))
    return out
