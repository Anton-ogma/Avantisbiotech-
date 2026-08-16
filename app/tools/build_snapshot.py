"""Сборка автономного снимка приложения (Р-38, Р-40).

Зачем: приложение показывают там, где бэкенда нет — на совещании, на планшете,
в переписке. Снимок — это те же ответы API, вшитые в страницу; клиент читает их
из `window.__DIERS_SNAPSHOT__` и в сеть не ходит вовсе (Р-23, контур замкнут).

Почему скрипт лежит в репозитории, а не собирается вручную: снимок обязан
воспроизводиться. Собранный «как-то раз» снимок расходится с приложением молча —
и первым, что он покажет, будет вчерашняя правда.

Запуск:  PYTHONPATH=packages:. python -m tools.build_snapshot
Результат: apps/web/public/snapshot.js
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "packages", ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

OUT = ROOT / "apps" / "web" / "public" / "snapshot.js"


async def build() -> None:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    os.environ["DIERS_DATABASE_URL"] = f"sqlite+aiosqlite:///{tmp.name}"

    import apps.api.db as db_mod
    import apps.api.settings as settings_mod
    settings_mod.get_settings.cache_clear()
    db_mod._engine = None
    db_mod._sessionmaker = None

    from httpx import ASGITransport, AsyncClient

    from apps.api.ingest_real import ingest as ingest_real
    from apps.api.main import app
    from apps.api.models import Base
    from apps.api.seed import seed

    async with db_mod.engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await seed()
    await ingest_real()

    headers = {"X-Actor-Ref": "clinician-1", "X-Actor-Role": "clinician"}
    snap: dict[str, object] = {}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://s") as c:
        async def grab(path: str, method: str = "GET") -> object | None:
            r = await (c.post(path, headers=headers, json={}) if method == "POST"
                       else c.get(path, headers=headers))
            if r.status_code >= 400:
                print(f"  ⚠ {path} → {r.status_code}")
                return None
            snap[path] = r.json()
            return snap[path]

        for path in ("/platform", "/params", "/sessions",
                     "/emg/muscles", "/emg/montages",
                     "/research/repeatability", "/research/progress"):
            await grab(path)

        # Печатный протокол прибора — необязательный локальный файл. В
        # репозитории его нет: иллюстрации DIERS — чужие материалы, а
        # реконструкция поверхности принадлежит конкретному обследованию.
        # Без него снимок собирается целиком, только без оригинальных картинок.
        pdf = os.environ.get("DIERS_SNAPSHOT_PROTOCOL_PDF")
        if pdf and Path(pdf).exists():
            await _attach_protocol(c, headers, Path(pdf))
        elif pdf:
            print(f"  ⚠ протокол {pdf} не найден — снимок без иллюстраций")

        # Демонстрационный монтаж на первой сессии: экран монтажа в снимке
        # должен показывать заполненный случай, а не пустую форму.
        first = ((await c.get("/sessions", headers=headers)).json() or [None])[0]
        if first:
            await c.put(f"/sessions/{first['id']}/montage", headers=headers, json={
                "template": "TMJ_PANEL",
                "channels": [
                    {"label": "CH1", "muscle": "MASSETER", "side": "L"},
                    {"label": "CH2", "muscle": "MASSETER", "side": "R"},
                    {"label": "CH3", "muscle": "TEMPORALIS", "side": "L"},
                    {"label": "CH4", "muscle": "TEMPORALIS", "side": "R"},
                    {"label": "CH5", "muscle": "SCM", "side": "L"},
                    {"label": "CH6", "muscle": "SCM", "side": "R"},
                    {"label": "CH7", "muscle": "TRAPEZIUS", "side": "L"},
                    {"label": "CH8", "muscle": "TRAPEZIUS", "side": "R"},
                ],
                "note": "демонстрационный монтаж: миограф подписывает каналы CH1…CH8",
            })

        sessions = snap.get("/sessions") or []
        for s in sessions:                                      # type: ignore[union-attr]
            sid = s["id"]
            await grab(f"/sessions/{sid}/analyze", method="POST")
            # Один ключ на сессию: /compare отдаёт ВСЕ пробы, клиент фильтрует
            # столбцы локально. Раскладывать сюда комбинации проб нельзя — их
            # экспоненциально много, и снимок молча ограничил бы сравнение.
            for path in (f"/sessions/{sid}/measurements", f"/sessions/{sid}/crossmodal",
                         f"/sessions/{sid}/compare", f"/sessions/{sid}/figures",
                         f"/sessions/{sid}/montage"):
                await grab(path)
            await grab(f"/sessions/{sid}/interim", method="POST")

    body = json.dumps(snap, ensure_ascii=False, separators=(",", ":"))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        "/* Автономный снимок. Собран tools/build_snapshot.py — вручную не править. */\n"
        f"window.__DIERS_SNAPSHOT__ = {body};\n",
        encoding="utf-8",
    )
    figures = sum(len(v.get("figures", [])) for k, v in snap.items()  # type: ignore[union-attr]
                  if k.endswith("/figures"))
    print(f"снимок: {len(snap)} ключей, {figures} иллюстраций, "
          f"{OUT.stat().st_size // 1024} КБ → {OUT}")


async def _attach_protocol(client, headers: dict[str, str], pdf: Path) -> None:
    """Догружает печатный протокол к пробе, куда он относится по условию.

    Проба ищется по метке условия из самого протокола через алиасы реестра —
    угадывать здесь, что «лев окк» это латеротрузия, нельзя (Р-36).
    """
    from importers import parse_blob

    from apps.api.services.bundle import bundle_from_settings
    from apps.api.settings import get_settings

    blob = pdf.read_bytes()
    _, results = parse_blob(blob)
    label = results[0].raw_row.get("condition_label", "")
    spec = bundle_from_settings(get_settings()).probes.by_alias(label)
    if spec is None:
        print(f"  ⚠ условие «{label}» не сопоставлено пробе — протокол не приложен")
        return

    for s in (await client.get("/sessions", headers=headers)).json():
        trials = (await client.get(f"/sessions/{s['id']}/measurements", headers=headers)).json()
        for trial in trials["trials"]:
            if trial["probe_code"] != spec.code:
                continue
            r = await client.post(
                f"/sessions/{s['id']}/imports?trial_id={trial['trial_id']}", headers=headers,
                files={"file": (pdf.name, blob, "application/pdf")},
            )
            print(f"  протокол → {spec.code}: {r.status_code} {r.json().get('status')}")
            return
    print(f"  ⚠ проба {spec.code} не найдена ни в одной сессии — протокол не приложен")


if __name__ == "__main__":
    asyncio.run(build())
