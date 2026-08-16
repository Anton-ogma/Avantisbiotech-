"""Порождение блока ЭМГ реестра и порогов из каталога мышц (Р-42).

Коды параметров, принадлежность области тела и распознавание меток каналов
обязаны идти из одного источника. Раньше они жили в трёх местах — в реестре,
в раскладке §14.3 и в словаре парсера — и расходились при каждом пополнении:
мышца появлялась в одном списке и отсутствовала в двух других.

Теперь источник один — `packages/config/emg/muscles.yaml`, а этот скрипт
переносит его в реестр и пороги. Правится КАТАЛОГ, а не порождённые файлы.

Запуск:
    PYTHONPATH=packages:. python -m tools.gen_emg_registry <из> <в>
    например: python -m tools.gen_emg_registry 2026.5 2026.7
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "packages", ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from domain.config import load_muscles  # noqa: E402

CONFIG = ROOT / "packages" / "config"
#: Demo-пороги. Назначены по единице измерения, а не измерены: замена приходит
#: из режима повторяемости (Этап 1.5), и до неё суждения о значимости неверны.
DEMO_RMS_SDC = 6.0
DEMO_ASYM_SDC = 12.0


def registry_block() -> str:
    lines = [
        "  # ── ЭМГ: порождено из packages/config/emg/muscles.yaml (Р-42) ──────────────",
        "  # Правится КАТАЛОГ, а не этот блок: коды, области тела и распознавание",
        "  # меток каналов обязаны идти из одного источника, иначе расходятся.",
        "  # Регенерация: python -m tools.gen_emg_registry <из> <в>",
        "",
    ]
    for m in load_muscles().muscles:
        if not m.surface:
            continue          # подписать канал недоступной мышцей нельзя
        for side, ru in (("L", "слева"), ("R", "справа")):
            lines += [
                f"  EMG_RMS_{m.code}_{side}:",
                f'    label_ru: "{m.label_ru}, {ru}"',
                "    modality: emg", "    unit: uV", "    domain: muscle",
                "    direction: unknown", "    in_pi: false", "    weight: 0.0",
            ]
        lines += [
            f"  EMG_ASYM_{m.code}:",
            f'    label_ru: "Асимметрия: {m.label_ru.lower()}"',
            "    modality: emg", "    unit: pct", "    domain: muscle",
            "    direction: unknown", "    in_pi: false", "    weight: 0.0",
        ]
    return "\n".join(lines) + "\n"


def thresholds_block() -> str:
    lines = [
        "  # ЭМГ — demo-пороги, порождены из каталога мышц (Р-42): RMS 6 мкВ,",
        "  # асимметрия 12 %. Значения назначены, а не измерены; замена — Этап 1.5.",
    ]
    for m in load_muscles().muscles:
        if not m.surface:
            continue
        lines += [f"  EMG_RMS_{m.code}_L: {DEMO_RMS_SDC}",
                  f"  EMG_RMS_{m.code}_R: {DEMO_RMS_SDC}",
                  f"  EMG_ASYM_{m.code}: {DEMO_ASYM_SDC}"]
    return "\n".join(lines) + "\n"


def main(src: str, dst: str) -> int:
    reg_src = CONFIG / "registry" / f"param_registry_{src}.yaml"
    if not reg_src.exists():
        print(f"нет {reg_src}", file=sys.stderr)
        return 1
    t = reg_src.read_text()
    start = t.index("  EMG_RMS_")
    end = t.index("  # ── Myoline")
    t = t[:start] + registry_block() + "\n" + t[end:]
    t = t.replace(f'version: "{src}"\nparams:', f'version: "{dst}"\nparams:', 1)
    (CONFIG / "registry" / f"param_registry_{dst}.yaml").write_text(t)

    thr = (CONFIG / "thresholds" / f"sdc_demo-{src}.yaml").read_text()
    thr = thr.replace(f'version: "demo-{src}"', f'version: "demo-{dst}"', 1)
    block = re.search(r"  # ЭМГ.*?\n(?:  EMG_[A-Z_]+: [\d.]+\n)+", thr, re.S)
    if block is None:
        print("не нашёл блок порогов ЭМГ", file=sys.stderr)
        return 1
    thr = thr[:block.start()] + thresholds_block() + thr[block.end():]
    (CONFIG / "thresholds" / f"sdc_demo-{dst}.yaml").write_text(thr)

    prof = (CONFIG / "profiles" / f"profile_{src}.yaml").read_text()
    (CONFIG / "profiles" / f"profile_{dst}.yaml").write_text(
        prof.replace(f'version: "{src}"', f'version: "{dst}"', 1))

    surface = sum(1 for m in load_muscles().muscles if m.surface)
    print(f"реестр {dst}: {surface} мышц → {surface * 3} кодов ЭМГ")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
