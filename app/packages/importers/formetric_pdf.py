"""DIERS formetric 4D — печатный протокол «Parameter_F4_Dynamic4D» (PDF).

Реальный путь клиники: DICAM печатает протокол, из него берётся текстовый слой.
Формат хуже CSV/XML — раскладка зависит от версии печати, — поэтому CSV остаётся
предпочтительным (§5.2). Но игнорировать фактически существующий путь нельзя.

Две ловушки настоящего протокола, обе покрыты тестами:

1. **Сторона словом, а не знаком.** «17 мм Прав.», «1° Лев.» — прибор печатает
   модуль и сторону. Канон (§5.3): вправо и вперёд положительно.

2. **Границы размаха печатаются в порядке фазы цикла, а не по возрастанию.**
   «20 мм Прав. - 6 мм Прав.» — это НЕ интервал от 20 до 6. Наивный разбор
   «первое — минимум» даёт вывернутый интервал и отрицательный размах.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .base import Figure, ParseResult, register

#: Порог «это не оформление, а содержательная картинка». Ниже — логотипы,
#: линейки, разделители: у реального протокола это 1–60 px по стороне.
_MIN_SIDE = 80
#: Напечатанное значение — низкая широкая полоса. Различаем по геометрии:
#: содержания растра мы не читаем, см. `_figures`.
_CAPTION_MAX_H = 100
_CAPTION_MIN_RATIO = 2.0

#: Подпись параметра в протоколе → (код значения, код размаха).
ROW_MAP: dict[str, tuple[str, str]] = {
    "Угол кифоза ICT-ITL (макс.)": ("DYN_KYPHOTIC_ANGLE_ICT_ITL_MAX", "DYN_KYPHOTIC_ANGLE_ICT_ITL_ROM"),
    "Угол лордоза ITL-ILS (макс.)": ("DYN_LORDOTIC_ANGLE_ITL_ILS_MAX", "DYN_LORDOTIC_ANGLE_ITL_ILS_ROM"),
    "Ротация таза": ("DYN_PELVIC_ROTATION", "DYN_PELVIC_ROTATION_ROM"),
    "Перекос таза": ("DYN_PELVIC_OBLIQUITY", "DYN_PELVIC_OBLIQUITY_ROM"),
    "Сагиттальный дисбаланс VP-DM": ("DYN_SAGITTAL_IMBALANCE_VP_DM", "DYN_SAGITTAL_IMBALANCE_VP_DM_ROM"),
}

#: Знаковые соглашения (§5.3). Канон: вправо / вперёд — положительно.
SIDE_SIGN: dict[str, float] = {
    "Прав.": 1.0, "Прав": 1.0, "R": 1.0,
    "Лев.": -1.0, "Лев": -1.0, "L": -1.0,
    "A": 1.0,      # anterior — вперёд
    "P": -1.0,     # posterior; в имеющемся протоколе не встречается — см. Р-36
}

_MEASURE = re.compile(r"(-?\d+(?:[.,]\d+)?)\s*(°|мм|mm)\s*([А-Яа-яA-Z.]+)?")
_SPEED = re.compile(r"СКОРОСТЬ\s+([\d.,]+)\s*(km/h|км/ч)")
_HEADER = re.compile(r"Parameter_F4_(\w+)\s*-\s*(\d{2}\.\d{2}\.\d{4})\s*\((\d{2}:\d{2})\)")


def classify_figure(width: int, height: int) -> str:
    """Что за растр — по геометрии, а не по содержанию (см. `Figure.kind`).

    Порядок проверок существенен: подпись «11° Прав.» ниже порога стороны,
    и проверь мы сначала размер, она попала бы в оформление и потерялась.
    """
    if height <= _CAPTION_MAX_H and width >= _CAPTION_MIN_RATIO * height:
        return "caption"
    if width < _MIN_SIDE or height < _MIN_SIDE:
        return "decor"
    return "render"


@dataclass(frozen=True, slots=True)
class Measure:
    value: float
    unit: str


def _parse_measure(chunk: str) -> Measure | None:
    m = _MEASURE.search(chunk)
    if m is None:
        return None
    magnitude = float(m.group(1).replace(",", "."))
    unit = "deg" if m.group(2) == "°" else "mm"
    side = (m.group(3) or "").strip()
    return Measure(magnitude * SIDE_SIGN.get(side, 1.0), unit)


def parse_range(chunk: str) -> tuple[float, float] | None:
    """Разбор «20 мм Прав. - 6 мм Прав.» и «1° Лев. - 7° Прав.».

    Возвращает (min, max) в каноническом знаке. Печатный порядок границ
    соответствует фазе цикла и не гарантирует возрастания — сортируем явно.
    """
    parts = re.split(r"\s+-\s+", chunk.strip())
    if len(parts) != 2:
        return None
    a, b = _parse_measure(parts[0]), _parse_measure(parts[1])
    if a is None or b is None:
        return None
    return (min(a.value, b.value), max(a.value, b.value))


@register
class FormetricPdfProtocolParser:
    format_id = "formetric-pdf-protocol-v1"
    modality = "formetric_dynamic"

    def detect(self, blob: bytes) -> bool:
        head = blob[:4096]
        if head.startswith(b"%PDF"):
            return True                      # разбор текста — в parse()
        try:
            text = blob.decode("utf-8")
        except UnicodeDecodeError:
            return False
        return "Parameter_F4_" in text and "ДИАПАЗОН ДВИЖЕНИЯ" in text

    def parse(self, blob: bytes) -> list[ParseResult]:
        """Разбирает ВСЕ разделы протокола, а не первый.

        Настоящий отчёт — многостраничный: «Parameter_F4_Dynamic4D» повторяется
        для каждого условия («лев окк», «прав окк», «нейтраль»). Разбор целиком
        как одного документа давал молчаливую порчу: метка условия бралась от
        первого раздела, а значения — от последнего, потому что одноимённые
        строки перетирали друг друга. Ошибки при этом не возникало, и результат
        выглядел правдоподобно — худший вид отказа из возможных.
        """
        sections = self._sections(blob)
        if not sections:
            raise ValueError("не протокол Parameter_F4_*")
        return [self._parse_section(text, figures, len(sections))
                for text, figures in sections]

    def _parse_section(self, text: str, figures: list[Figure],
                       total_sections: int) -> ParseResult:
        header = _HEADER.search(text)
        variant = header.group(1) if header else "unknown"
        params: dict[str, float] = {}
        unmapped: dict[str, str] = {}
        flags: list[str] = []

        speed = _SPEED.search(text)
        if speed:
            params["GAIT_SPEED_KMH"] = float(speed.group(1).replace(",", "."))

        for line in text.splitlines():
            line = line.strip()
            matched = False
            for label, (value_code, rom_code) in ROW_MAP.items():
                if not line.startswith(label):
                    continue
                matched = True
                rest = line[len(label):].strip()
                # Значение и диапазон разделены первым вхождением « - » внутри
                # диапазона; значение — до начала второй пары «число+единица».
                measures = list(_MEASURE.finditer(rest))
                if not measures:
                    flags.append(f"missing_landmark:{value_code}")
                    break
                first = _parse_measure(rest[measures[0].start():measures[0].end()])
                if first is not None:
                    params[value_code] = round(first.value, 3)
                if len(measures) >= 3:
                    rng = parse_range(rest[measures[1].start():])
                    if rng is not None:
                        lo, hi = rng
                        params[rom_code] = round(hi - lo, 3)
                        params[f"{rom_code}_MIN"] = round(lo, 3)
                        params[f"{rom_code}_MAX"] = round(hi, 3)
                else:
                    flags.append(f"missing_range:{rom_code}")
                break
            if not matched and line and ":" in line:
                unmapped[line[:80]] = ""

        if not params:
            flags.append("no_canonical_columns")
        if total_sections > 1:
            # Раздел одного многостраничного отчёта. Метка нужна ниже по потоку:
            # разделы попадут в РАЗНЫЕ пробы, и это должно быть видно оператору.
            flags.append(f"multi_section_protocol:{total_sections}")
        if any(f.kind == "caption" for f in figures):
            # Значения, напечатанные на иллюстрации растром, в текстовый слой не
            # попадают. Прибор так печатает угловой перекос таза: в таблице он в
            # миллиметрах, на схеме — в градусах. Разбором это не достаётся.
            flags.append("figure_values_not_in_text_layer")

        return ParseResult(
            format_id=self.format_id,
            modality=self.modality,
            device_sw_version=variant,
            params=params,
            unmapped=unmapped,
            quality_flags=flags,
            raw_row={"variant": variant,
                     "date": header.group(2) if header else "",
                     "time": header.group(3) if header else "",
                     "condition_label": self._condition(text)},
            figures=figures,
        )

    def _sections(self, blob: bytes) -> list[tuple[str, list[Figure]]]:
        """Режет отчёт на разделы по заголовку «Parameter_F4_*».

        Единица деления — заголовок, а не страница: раздел может занимать
        несколько страниц, а одна страница — нести только продолжение таблицы.
        Иллюстрации страницы отходят разделу, который на этой странице идёт
        (или продолжается): привязать картинку точнее нечем, а выбросить —
        значит потерять данные молча (§5.1).
        """
        sections: list[tuple[list[str], list[Figure]]] = []
        for text, figures in self._pages(blob):
            starts = [m.start() for m in _HEADER.finditer(text)]
            if not starts:
                if sections:
                    sections[-1][0].append(text)
                    sections[-1][1].extend(figures)
                continue
            head = text[:starts[0]].strip()
            if head and sections:
                sections[-1][0].append(head)      # хвост предыдущего раздела
            bounds = starts + [len(text)]
            for i, begin in enumerate(starts):
                chunk = text[begin:bounds[i + 1]]
                # Иллюстрации страницы получает ПЕРВЫЙ её раздел: печать ведёт
                # схемы сразу за заголовком, а разносить их по позиции в потоке
                # нельзя — координат у растра в текстовом слое нет.
                sections.append(([chunk], figures if i == 0 else []))
        return [("\n".join(parts), figs) for parts, figs in sections]

    def _pages(self, blob: bytes) -> list[tuple[str, list[Figure]]]:
        """Текст и растры по страницам. Для не-PDF — одна условная страница."""
        if not blob.startswith(b"%PDF"):
            return [(blob.decode("utf-8", errors="replace"), [])]
        try:
            import io

            from pypdf import PdfReader
        except ImportError as e:                           # pragma: no cover
            raise ValueError("для разбора PDF нужен pypdf") from e
        out: list[tuple[str, list[Figure]]] = []
        for page in PdfReader(io.BytesIO(blob)).pages:
            out.append(((page.extract_text() or ""), self._page_figures(page)))
        return out

    @staticmethod
    def _page_figures(page) -> list[Figure]:
        try:
            images = list(page.images)
        except Exception:                                  # pragma: no cover
            return []            # битое вложение — не повод терять таблицу
        out: list[Figure] = []
        for im in images:
            try:
                data = im.data
                w, h = im.image.width, im.image.height
            except Exception:                              # pragma: no cover
                continue          # без Pillow размеров нет; таблицу это не рушит
            kind = classify_figure(w, h)
            if kind == "decor":
                continue
            mime = "image/png" if data[:4] == b"\x89PNG" else "image/jpeg"
            out.append(Figure(name=im.name, mime=mime, width=w, height=h,
                              kind=kind, data=data))
        return out


    @staticmethod
    def _condition(text: str) -> str:
        """Метка условия пробы, как её пишет клиника: «лев окк» и подобное.

        Сопоставление метки с кодом пробы делает реестр проб через aliases —
        догадываться здесь, что «окк» это латеротрузия, нельзя (Р-36).
        """
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        for i, ln in enumerate(lines):
            if ln.startswith("Parameter_F4_") and i + 1 < len(lines):
                return lines[i + 1]
        return ""

    @staticmethod
    def _text(blob: bytes) -> str:
        if not blob.startswith(b"%PDF"):
            return blob.decode("utf-8", errors="replace")
        try:
            import io

            from pypdf import PdfReader
        except ImportError as e:                       # pragma: no cover
            raise ValueError("для разбора PDF нужен pypdf") from e
        reader = PdfReader(io.BytesIO(blob))
        return "\n".join((p.extract_text() or "") for p in reader.pages)
