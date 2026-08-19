"""CADIAX 4 (Gamma Dental) — кондилография, блок «Numerical Analysis».

Модальность §4 ТЗ: condylography_recordings + condylar_metrics. Сопоставление
с формометрией — уровень M синхронизации (§6.2): по коду пробы, со сверкой
excursion_mm; источник этой величины — строка QUANTITY / Maximum excursion distance.

Прибор печатает таблицу «показатель × сторона (Right/Left)». Разбор рассчитан
на текст, скопированный из окна числового анализа или из печатной формы.
Ручной ввод сводных показателей (§5.2) использует те же канонические коды.
"""
from __future__ import annotations

import re

from .base import ParseResult, register

#: Подпись CADIAX → шаблон канонического кода. {side} → R/L.
ROW_MAP: dict[str, str] = {
    "Maximum excursion distance": "CDG_MAX_EXCURSION_{side}",
    "Final": "CDG_RETRAL_STABILITY_{side}",
    "Distance": "CDG_START_END_DIFF_{side}",
    "Maximum speed": "CDG_MAX_SPEED_{side}",
    "Kobs coefficient": "CDG_KOBS_{side}",
}

#: Подписи внутри секций, где строка «3 mm / 5 mm / 10 mm» повторяется:
#: смысл задаёт заголовок секции, а не сама строка.
SECTION_MAP: dict[str, str] = {
    "SCI ANGLES": "CDG_SCI_{mm}MM_{side}",
    "TCI ANGLES": "CDG_TCI_{mm}MM_{side}",
    "REPRODUCIBILITY": "CDG_REPRODUCIBILITY_{mm}MM_{side}",
}

SINGLE_MAP: dict[str, str] = {
    "Ratio": "CDG_QUANTITY_SYMMETRY",
    "Angle": "CDG_HINGE_AXIS_ANGLE",
    "Maximum rotation angle": "CDG_MAX_ROTATION_GAMMA",
}

MOVEMENT_ALIASES: dict[str, str] = {
    "открывание/закрывание": "CDG_OPEN_CLOSE",
    "протрузия/ретрузия": "CDG_PROTRUSION_RETRUSION",
    "медиотрузия влево": "CDG_MEDIOTRUSION_LEFT",
    "медиотрузия вправо": "CDG_MEDIOTRUSION_RIGHT",
    "opening/closing": "CDG_OPEN_CLOSE",
    "protrusion/retrusion": "CDG_PROTRUSION_RETRUSION",
}

_NUM = re.compile(r"[−-]?\d+(?:[.,]\d+)?")
_HARMONY = re.compile(r"Value\s+([−\-\d.,]+)\s*°?/mm\s+([−\-\d.,]+)")
_NAME = re.compile(r"Name:\s*(.+)")
_SYSTEM = re.compile(r"System:\s*(.+)")


def _num(raw: str) -> float | None:
    """CADIAX печатает минус как U+2212 и десятичную запятую."""
    s = raw.replace("−", "-").replace(",", ".").strip()
    try:
        return float(s)
    except ValueError:
        return None


@register
class CadiaxNumericParser:
    format_id = "cadiax-numeric-v4"
    modality = "condylography"

    def detect(self, blob: bytes) -> bool:
        try:
            text = blob.decode("utf-8")
        except UnicodeDecodeError:
            return False
        return "CADIAX" in text and ("SCI ANGLES" in text or "Numerical Analysis" in text)

    def parse(self, blob: bytes) -> list[ParseResult]:
        text = blob.decode("utf-8", errors="replace")
        params: dict[str, float] = {}
        unmapped: dict[str, str] = {}
        flags: list[str] = []
        section = ""

        name = _NAME.search(text)
        movement = (name.group(1).strip() if name else "").lower()
        movement_code = next(
            (code for alias, code in MOVEMENT_ALIASES.items() if alias in movement), None
        )
        if movement_code is None and movement:
            flags.append(f"unknown_movement:{movement[:40]}")

        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            upper = line.upper()
            for key in (*SECTION_MAP, "QUANTITY SYMMETRY", "ANGULATION SYMMETRY SCI",
                        "SIMULTANEOUS MOVEMENT", "QUANTITY OF ROTATION", "HARMONY OF TRANS"):
                if upper.startswith(key):
                    section = key
                    break

            harmony = _HARMONY.search(line)
            if harmony:
                params["CDG_HARMONY_R"] = float(
                    harmony.group(1).replace("−", "-").replace(",", "."))
                params["CDG_HARMONY_L"] = float(
                    harmony.group(2).replace("−", "-").replace(",", "."))
                continue

            numbers = [v for v in (_num(m.group()) for m in _NUM.finditer(line)) if v is not None]

            # Секции с повторяющимися строками 3/5/10 mm
            mm_match = re.match(r"^(3|5|10)\s*mm\b", line)
            if mm_match and section in SECTION_MAP and len(numbers) >= 3:
                mm = mm_match.group(1)
                template = SECTION_MAP[section]
                params[template.format(mm=mm, side="R")] = numbers[1]
                params[template.format(mm=mm, side="L")] = numbers[2]
                continue
            if mm_match and section == "ANGULATION SYMMETRY SCI" and len(numbers) >= 2:
                continue    # обработано ниже по подписи "Ratio at N mm"

            ratio = re.match(r"^Ratio at (3|5|10) mm", line)
            if ratio and numbers:
                params[f"CDG_SCI_SYMMETRY_{ratio.group(1)}MM"] = numbers[-1]
                continue

            for label, template in ROW_MAP.items():
                if line.startswith(label) and len(numbers) >= 2:
                    params[template.format(side="R")] = numbers[-2]
                    params[template.format(side="L")] = numbers[-1]
                    break
            else:
                for label, code in SINGLE_MAP.items():
                    if line.startswith(label) and numbers:
                        params[code] = numbers[-1]
                        break
                else:
                    if numbers and not line.startswith(("at time", "Initial")):
                        unmapped[line[:60]] = ""

        # Метрология прибора: собственная воспроизводимость CADIAX. Разница между
        # сторонами на порядок — признак неравного качества записи, а не биологии.
        for mm in (3, 5, 10):
            right = params.get(f"CDG_REPRODUCIBILITY_{mm}MM_R")
            left = params.get(f"CDG_REPRODUCIBILITY_{mm}MM_L")
            if (right is not None and left is not None and max(right, left) > 0
                    and (min(right, left) == 0
                         or max(right, left) / max(min(right, left), 1e-6) >= 5)):
                flags.append(f"reproducibility_side_mismatch:{mm}mm")
                break

        if not params:
            flags.append("no_canonical_columns")

        system = _SYSTEM.search(text)
        return [ParseResult(
            format_id=self.format_id,
            modality=self.modality,
            device_sw_version=system.group(1).strip() if system else None,
            params=params,
            unmapped=unmapped,
            quality_flags=flags,
            raw_row={"movement": movement, "movement_code": movement_code or ""},
        )]
