"""Парсеры приборных форматов (§5 ТЗ).

MUST: один парсер на версию формата, выбор через detect(); молчаливый пропуск
запрещён — нераспознанный файл остаётся в очереди со статусом unrecognized.
"""
from .base import (PARSERS, Figure, ParseResult, Parser, ParserNotFound, detect_parser,
                   parse_blob)
from .cadiax_numeric import CadiaxNumericParser
from .emg_csv import EmgCsvParser, MyolineCsvParser
from .formetric_csv import FormetricCsvParser
from .formetric_pdf import FormetricPdfProtocolParser
from .myoline_pdf import MyolinePdfParser
from .pedoscan_csv import PedoscanCsvParser
from .screenshot import ScreenshotParser

__all__ = [
    "PARSERS", "Figure", "ParseResult", "Parser", "ParserNotFound",
    "detect_parser", "parse_blob", "FormetricCsvParser", "PedoscanCsvParser",
    "FormetricPdfProtocolParser", "CadiaxNumericParser", "EmgCsvParser", "MyolineCsvParser",
    "ScreenshotParser", "MyolinePdfParser",
]
