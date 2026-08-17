"""Снимки экрана приборного ПО: приём как свидетельства (Р-44).

Проводной миограф часто не даёт выгрузки вообще — оператор снимает экран. Такой
файл до сих пор отвергался как нераспознанный, то есть данные терялись целиком.

ЧТО ЗДЕСЬ РАСПОЗНАЁТСЯ. Тип экрана — по геометрии и палитре: соотношение
сторон, доля тёмного, наличие сетки. Этого хватает, чтобы отнести снимок к
модальности и предложить нужную форму ввода.

ЧТО ЗДЕСЬ НЕ РАСПОЗНАЁТСЯ — ЧИСЛА. Это не нехватка библиотеки, а требование
§5.2а: у каждого значения должен быть прослеживаемый источник и знак. Значение,
полученное распознаванием текста, происхождения не имеет: сверить его не с чем,
а ошибка распознавания «8» вместо «3» даёт правдоподобное измерение, которого
никто не делал. Поэтому снимок хранится картинкой, а числа с него вводит
человек — тем же механизмом ручной транскрипции, что и подписи на иллюстрациях
протокола DIERS, со сверкой по совпадающим кодам.

Отдельно: OCR потребовал бы либо внешнего сервиса (запрещено ФЗ-152 ст. 12 и
Р-23 — контур замкнут), либо движка в образе. Второе технически возможно и
ничего в этом решении не меняет: запрет на числа из растра — методический,
а не технический.
"""
from __future__ import annotations

from .base import Figure, ParseResult, register

#: Минимальная сторона снимка экрана. Меньше — значок или обрезок, и снимком
#: экрана прибора это не является.
_MIN_SIDE = 240

MAGIC = {
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"\xff\xd8\xff": "image/jpeg",
    b"BM": "image/bmp",
}


def sniff_mime(blob: bytes) -> str | None:
    for magic, mime in MAGIC.items():
        if blob.startswith(magic):
            return mime
    # TIFF: два порядка байтов
    if blob[:4] in (b"II*\x00", b"MM\x00*"):
        return "image/tiff"
    return None


def classify_screen(width: int, height: int, dark_share: float) -> str:
    """Тип экрана по геометрии и палитре — без чтения содержимого.

    Различаются три случая, и различие практическое: под каждый нужна своя
    форма ручного ввода.

    • `trace` — тёмный широкий экран: развёртка сигнала во времени. Отсюда
      берут амплитуды по каналам.
    • `report` — светлый экран близкий к листу: таблица показателей.
    • `unknown` — не похоже ни на то, ни на другое. Снимок принимается и
      хранится, но форма не предлагается: угадывать не на чем.
    """
    ratio = width / height if height else 0.0
    if dark_share >= 0.5 and ratio >= 1.3:
        return "trace"
    if dark_share < 0.5 and 0.6 <= ratio <= 1.6:
        return "report"
    return "unknown"


@register
class ScreenshotParser:
    """Снимок экрана прибора: одна иллюстрация, ноль канонических значений."""

    format_id = "device-screenshot-v1"
    modality = "screenshot"

    def detect(self, blob: bytes) -> bool:
        return sniff_mime(blob) is not None

    def parse(self, blob: bytes) -> list[ParseResult]:
        mime = sniff_mime(blob)
        if mime is None:
            raise ValueError("не изображение")
        width, height, dark = _probe(blob)
        if width and height and (width < _MIN_SIDE or height < _MIN_SIDE):
            raise ValueError(
                f"изображение {width}×{height}: слишком мало для снимка экрана прибора"
            )
        kind = classify_screen(width, height, dark)
        return [ParseResult(
            format_id=self.format_id,
            modality=self.modality,
            device_sw_version=None,
            # Ни одного значения. Числа со снимка вводит человек: у величины из
            # растра нет прослеживаемого источника (§5.2а).
            params={},
            unmapped={},
            quality_flags=[
                "screenshot_values_require_manual_entry",
                f"screen_kind:{kind}",
            ],
            raw_row={"screen_kind": kind, "width": str(width), "height": str(height)},
            figures=[Figure(name="screenshot", mime=mime, width=width, height=height,
                            kind="render", data=blob)],
        )]


def _probe(blob: bytes) -> tuple[int, int, float]:
    """Размер и доля тёмного. Без Pillow — только размер из заголовка PNG."""
    try:
        import io

        from PIL import Image
    except ImportError:                                    # pragma: no cover
        return (*_png_size(blob), 0.0)
    try:
        with Image.open(io.BytesIO(blob)) as im:
            width, height = im.size
            # Доля тёмного считается по уменьшенной копии: точность здесь не
            # нужна, а полный проход по 4К-снимку стоит секунды.
            small = im.convert("L").resize((32, 32))
            pixels = [small.getpixel((x, y)) for y in range(32) for x in range(32)]
            dark = sum(1 for p in pixels if p < 96) / len(pixels)
        return width, height, round(dark, 3)
    except Exception:                                      # pragma: no cover
        return (*_png_size(blob), 0.0)


def _png_size(blob: bytes) -> tuple[int, int]:
    if blob.startswith(b"\x89PNG") and len(blob) >= 24:
        return (int.from_bytes(blob[16:20], "big"), int.from_bytes(blob[20:24], "big"))
    return (0, 0)
