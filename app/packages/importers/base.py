from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


class ParserNotFound(Exception):
    """Формат не распознан. MUST §5.1: файл не пропускается молча."""


@dataclass(frozen=True, slots=True)
class Figure:
    """Иллюстрация из протокола прибора.

    Печатный протокол formetric несёт не только таблицу: реконструкцию спины,
    схему таза с линией перекоса, схему таза сверху с углом ротации. Часть
    величин напечатана ТОЛЬКО на иллюстрации — растром, вне текстового слоя,
    и парсером не читается. Выбрасывать такую картинку нельзя: молчаливая
    потеря данных запрещена (§5.1) ровно так же, как для неканонических
    столбцов, а оператору нужно видеть источник расхождения.

    `kind` — что это, по геометрии, а не по догадке о содержании:
      • `render`  — крупное изображение, реконструкция или схема;
      • `caption` — узкая полоса с напечатанным значением (высота ≤ 40 px);
      • `decor`   — логотип, линейка, разделитель.
    """
    name: str
    mime: str
    width: int
    height: int
    kind: str
    data: bytes
    #: Структуры, о которых говорит СТРАНИЦА, откуда взята иллюстрация:
    #: «spine», «pelvis», «feet», «knee». Определяются по печатному заголовку,
    #: а не по пикселям: заголовок прибор пишет сам, и это факт, а не догадка.
    #: Пусто — страница ни одной структуры не назвала.
    structures: tuple[str, ...] = ()
    page: int = 0


@dataclass(slots=True)
class ParseResult:
    format_id: str
    modality: str
    device_sw_version: str | None
    #: Канонические значения: код параметра → значение. Уже в канонических кодах
    #: и единицах, знаки приведены (§5.3).
    params: dict[str, float]
    #: Неканонические столбцы. Не выбрасываются: молчаливая потеря запрещена.
    unmapped: dict[str, str] = field(default_factory=dict)
    quality_flags: list[str] = field(default_factory=list)
    raw_row: dict[str, str] = field(default_factory=dict)
    #: Иллюстрации протокола в порядке появления. Пусто для табличных форматов.
    figures: list[Figure] = field(default_factory=list)


@runtime_checkable
class Parser(Protocol):
    format_id: str
    modality: str

    def detect(self, blob: bytes) -> bool: ...
    def parse(self, blob: bytes) -> list[ParseResult]: ...


PARSERS: list[Parser] = []


def register(parser_cls: type) -> type:
    """Декоратор регистрирует ЭКЗЕМПЛЯР: detect/parse — методы экземпляра,
    а реестр должен хранить готовые к вызову объекты."""
    PARSERS.append(parser_cls())
    return parser_cls


def detect_parser(blob: bytes) -> Parser:
    for p in PARSERS:
        if p.detect(blob):
            return p
    raise ParserNotFound("формат не распознан ни одним парсером")


def parse_blob(blob: bytes) -> tuple[Parser, list[ParseResult]]:
    parser = detect_parser(blob)
    return parser, parser.parse(blob)


# ── Общие утилиты разбора ────────────────────────────────────────────────────

def decode(blob: bytes) -> str:
    """MUST §5.2: кодировка определяется по содержимому, не по локали сервера.
    DICAM в русской локали нередко пишет Windows-1251."""
    for encoding in ("utf-8-sig", "utf-8", "cp1251", "latin-1"):
        try:
            return blob.decode(encoding)
        except UnicodeDecodeError:
            continue
    return blob.decode("utf-8", errors="replace")


def sniff_delimiter(header: str) -> str:
    """Европейский экспорт DICAM использует ';'. Определяем по содержимому."""
    counts = {d: header.count(d) for d in (";", "\t", ",")}
    return max(counts, key=lambda d: counts[d]) if max(counts.values()) else ";"


_NUM = re.compile(r"^-?\d+(?:[.,]\d+)?$")


def parse_number(raw: str) -> float | None:
    """MUST §5.2: десятичный разделитель определяется по содержимому значения.

    '12,5' — европейская запятая; '1,234.5' — тысячный разделитель.
    Никакой зависимости от локали процесса.
    """
    s = raw.strip().replace(" ", "").replace(" ", "")
    if not s:
        return None
    if s.count(",") and s.count("."):
        s = s.replace(",", "")                      # запятая = разряды
    elif s.count(",") == 1 and not s.count("."):
        s = s.replace(",", ".")                     # запятая = дробная часть
    if not _NUM.match(s):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def read_rows(blob: bytes) -> tuple[list[str], list[dict[str, str]]]:
    text = decode(blob)
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) < 2:
        raise ValueError("файл содержит меньше двух непустых строк")
    delimiter = sniff_delimiter(lines[0])
    reader = csv.DictReader(io.StringIO("\n".join(lines)), delimiter=delimiter)
    headers = [h.strip() for h in (reader.fieldnames or [])]
    rows = [{(k or "").strip(): (v or "").strip() for k, v in row.items()} for row in reader]
    return headers, rows
