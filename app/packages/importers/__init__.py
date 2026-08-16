"""Парсеры приборных форматов (§5 ТЗ).

MUST: один парсер на версию формата, выбор через detect(); молчаливый пропуск
запрещён — нераспознанный файл остаётся в очереди со статусом unrecognized.
"""
from .base import PARSERS, ParseResult, Parser, ParserNotFound, detect_parser, parse_blob
from .cadiax_numeric import CadiaxNumericParser
from .formetric_csv import FormetricCsvParser
from .formetric_pdf import FormetricPdfProtocolParser
from .pedoscan_csv import PedoscanCsvParser

__all__ = [
    "PARSERS", "ParseResult", "Parser", "ParserNotFound",
    "detect_parser", "parse_blob", "FormetricCsvParser", "PedoscanCsvParser",
    "FormetricPdfProtocolParser", "CadiaxNumericParser",
]
