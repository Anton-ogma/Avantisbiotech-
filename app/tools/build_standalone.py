"""Сборка одностраничного автономного приложения.

Собирает `dist/` и снимок в один HTML-файл: разметка, стили, скрипт и данные
внутри. Никаких внешних запросов — контур замкнут (Р-23), и это же делает файл
пригодным для показа там, где сети нет вовсе.

Запуск (после `npm run build` и `tools.build_snapshot`):
    PYTHONPATH=packages:. python -m tools.build_standalone
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "apps" / "web"
DIST = WEB / "dist"
OUT = DIST / "standalone.html"


def main() -> int:
    index = DIST / "index.html"
    if not index.exists():
        print("нет dist/index.html — сначала `npm run build`", file=sys.stderr)
        return 1
    snapshot = WEB / "public" / "snapshot.js"
    if not snapshot.exists():
        print("нет public/snapshot.js — сначала `python -m tools.build_snapshot`",
              file=sys.stderr)
        return 1

    html = index.read_text(encoding="utf-8")
    for tag, pattern, wrap in (
        ("css", r'<link[^>]+href="(/assets/[^"]+\.css)"[^>]*>', "<style>{}</style>"),
        ("js", r'<script[^>]+src="(/assets/[^"]+\.js)"[^>]*></script>',
         '<script type="module">{}</script>'),
    ):
        for match in list(re.finditer(pattern, html)):
            asset = DIST / match.group(1).lstrip("/")
            html = html.replace(match.group(0), wrap.format(asset.read_text(encoding="utf-8")))

    # Снимок должен встать ДО модуля приложения: клиент читает его при первом
    # запросе, а модуль исполняется сразу после разбора.
    html = html.replace("</head>", f"<script>{snapshot.read_text(encoding='utf-8')}</script>\n</head>")
    OUT.write_text(html, encoding="utf-8")
    print(f"автономная страница: {OUT.stat().st_size // 1024} КБ → {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
