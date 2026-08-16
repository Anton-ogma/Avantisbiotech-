"""DIERS pedoscan, экспорт CSV."""
from __future__ import annotations

from .base import ParseResult, parse_number, read_rows, register

COLUMN_MAP: dict[str, str] = {
    "Load Left %": "LOAD_SHARE_LEFT",
    "Load_Left_pct": "LOAD_SHARE_LEFT",
    "Belastung links %": "LOAD_SHARE_LEFT",
    "Load Right %": "LOAD_SHARE_RIGHT",
    "Load_Right_pct": "LOAD_SHARE_RIGHT",
    "Belastung rechts %": "LOAD_SHARE_RIGHT",
    "COP Path Length": "COP_PATH_LENGTH",
    "COP_Path_Length": "COP_PATH_LENGTH",
    "COP Area": "COP_AREA",
    "COP_Area": "COP_AREA",
}

MARKERS = ("COP Path", "COP_Path", "Load Left", "Belastung links")


@register
class PedoscanCsvParser:
    format_id = "pedoscan-csv-v2"
    modality = "pedoscan"

    def detect(self, blob: bytes) -> bool:
        try:
            headers, _ = read_rows(blob)
        except Exception:
            return False
        return any(m in " ".join(headers) for m in MARKERS)

    def parse(self, blob: bytes) -> list[ParseResult]:
        _, rows = read_rows(blob)
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
            left, right = params.get("LOAD_SHARE_LEFT"), params.get("LOAD_SHARE_RIGHT")
            if left is not None and right is not None and abs(left + right - 100) > 1.0:
                flags.append("load_share_sum_mismatch")
            out.append(ParseResult(
                format_id=self.format_id, modality=self.modality,
                device_sw_version=None, params=params, unmapped=unmapped,
                quality_flags=flags, raw_row=dict(row),
            ))
        return out
