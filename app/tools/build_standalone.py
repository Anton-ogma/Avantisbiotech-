"""Сборка автономной страницы приложения: разметка, стили, скрипт и данные в одном файле.

Два выхода, и различие между ними существенно:

  • `dist/standalone.html` — **полный документ**. Открывается двойным щелчком с
    диска, работает без сети (Р-23, контур замкнут).
  • `dist/artifact.html` — **фрагмент для `<body>`**, без `<!doctype>`, `<html>`,
    `<head>` и `<body>`. Публикатор артефакта оборачивает файл своим каркасом,
    и вложенный документ внутри `<body>` — уже не документ: разбор переносит
    содержимое внутренней `<head>` по своим правилам, а `<title>` и вовсе
    достаётся не тому каркасу. Отдавать туда полный документ было ошибкой.

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

TITLE = "DIERS · постуральный модуль"


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
    css = _inline(html, r'<link[^>]+href="(/assets/[^"]+\.css)"[^>]*>')
    js = _inline(html, r'<script[^>]+src="(/assets/[^"]+\.js)"[^>]*></script>')
    snap = snapshot.read_text(encoding="utf-8")

    # Порядок частей задан разбором, а не вкусом: <title> идёт первым, потому что
    # публикатор ищет его в начале файла; снимок — до модуля приложения, потому
    # что клиент читает его при первом же запросе.
    fragment = "\n".join([
        f"<title>{TITLE}</title>",
        f"<style>{css}</style>",
        '<div id="root"></div>',
        f"<script>{_guard(snap)}</script>",
        f'<script type="module">{js}</script>',
    ])
    (DIST / "artifact.html").write_text(fragment, encoding="utf-8")

    document = "\n".join([
        "<!doctype html>", '<html lang="ru">', "<head>",
        '<meta charset="UTF-8" />',
        '<meta name="viewport" '
        'content="width=device-width, initial-scale=1, viewport-fit=cover" />',
        '<meta name="color-scheme" content="light dark" />',
        f"<title>{TITLE}</title>",
        f"<style>{css}</style>",
        "</head>", "<body>", fragment.split("\n", 2)[2], "</body>", "</html>",
    ])
    (DIST / "standalone.html").write_text(document, encoding="utf-8")

    for name in ("artifact.html", "standalone.html"):
        print(f"{name}: {(DIST / name).stat().st_size // 1024} КБ")
    return 0


def _inline(html: str, pattern: str) -> str:
    """Содержимое ассетов, на которые ссылается index.html."""
    out = []
    for match in re.finditer(pattern, html):
        out.append((DIST / match.group(1).lstrip("/")).read_text(encoding="utf-8"))
    return "\n".join(out)


def _guard(script: str) -> str:
    """Экранирует последовательность, закрывающую <script> раньше времени.

    В данных её быть не должно, но проверка стоит дешевле, чем поиск причины
    пустой страницы: одна такая подстрока обрывает разбор скрипта, и дальше
    браузер читает JSON как разметку.
    """
    return script.replace("</script", "<\\/script")


if __name__ == "__main__":
    raise SystemExit(main())
