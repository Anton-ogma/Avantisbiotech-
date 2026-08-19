"""Иллюстрации приборного протокола: извлечение, хранение, выдача (Р-40).

PDF собирается здесь же, а не лежит фикстурой. Причина не в удобстве:
настоящий протокол несёт реконструкцию поверхности спины конкретного человека,
и класть такой файл в репозиторий нельзя — ПДн в модуль не попадают (Р-9).
Синтетический протокол проверяет ровно тот же путь: текстовый слой отдаёт
таблицу, растровые вложения отдают иллюстрации, подпись даёт флаг качества.
"""
import io
import os
import tempfile
import zlib

import pytest
import pytest_asyncio

os.environ.setdefault("DIERS_DATABASE_URL", "")

PROTOCOL_TEXT = (
    "Parameter_F4_Dynamic4D - 04.03.2025 (18:27)\n"
    "лев окк\n"
    "СКОРОСТЬ 3 km/h 3 km/h\n"
    "ПАРАМЕТР ЗНАЧЕНИЕ ДИАПАЗОН ДВИЖЕНИЯ\n"
    "Ротация таза 5° Прав. 1° Лев. - 7° Прав.\n"
    "Перекос таза 17 мм Прав. 20 мм Прав. - 6 мм Прав.\n"
)


def _jpeg(width: int, height: int) -> bytes:
    Image = pytest.importorskip("PIL.Image")
    buf = io.BytesIO()
    Image.new("RGB", (width, height), (200, 200, 200)).save(buf, "JPEG")
    return buf.getvalue()


def build_pdf(images: list[tuple[str, int, int]]) -> bytes:
    return build_pdf_with_text(PROTOCOL_TEXT, images)


def build_pdf_with_text(text: str, images: list[tuple[str, int, int]]) -> bytes:
    """Однастраничный PDF: текстовый слой + перечисленные растры.

    Собирается вручную, без генератора: нужен точный контроль над тем, что
    именно увидит парсер, — размеры вложений и есть предмет проверки.
    """
    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    # Текст рисуется по строкам; кириллица в PDF-строке не нужна — парсер
    # читает текстовый слой через pypdf, которому достаточно WinAnsi/UTF-16.
    lines = "".join(
        f"BT /F1 10 Tf 40 {760 - i * 14} Td <FEFF{s.encode('utf-16-be').hex().upper()}> Tj ET\n"
        for i, s in enumerate(text.splitlines())
    )
    content = lines.encode("latin-1")
    content_id = add(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(content), content))
    font_id = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
                  b"/Encoding /Identity-H >>")

    xobjects: list[tuple[str, int]] = []
    for name, w, h in images:
        data = _jpeg(w, h)
        oid = add(
            b"<< /Type /XObject /Subtype /Image /Width %d /Height %d "
            b"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode "
            b"/Length %d >>\nstream\n" % (w, h, len(data)) + data + b"\nendstream"
        )
        xobjects.append((name, oid))

    xo = b" ".join(b"/%s %d 0 R" % (n.encode(), i) for n, i in xobjects)
    page_id = add(
        b"<< /Type /Page /Parent 100 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 %d 0 R >> /XObject << %s >> >> "
        b"/Contents %d 0 R >>" % (font_id, xo, content_id)
    )
    pages_id = add(b"<< /Type /Pages /Kids [%d 0 R] /Count 1 >>" % page_id)
    root_id = add(b"<< /Type /Catalog /Pages %d 0 R >>" % pages_id)
    objects[page_id - 1] = objects[page_id - 1].replace(b"/Parent 100 0 R",
                                                        b"/Parent %d 0 R" % pages_id)

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    start = len(out)
    out += b"xref\n0 %d\n" % (len(objects) + 1)
    out += b"0000000000 65535 f \n"
    for off in offsets[1:]:
        out += b"%010d 00000 n \n" % off
    out += (b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n"
            % (len(objects) + 1, root_id, start))
    assert zlib  # импорт держится ради читаемости диффа, если появится /FlateDecode
    return bytes(out)


#: Геометрия — с настоящего протокола: реконструкция, схема таза, подпись, логотип.
SAMPLE_IMAGES = [("Im1", 60, 59), ("Im3", 615, 196), ("Im4", 228, 155), ("Im5", 756, 84)]


def test_pdf_yields_table_and_figures():
    from importers import parse_blob

    parser, results = parse_blob(build_pdf(SAMPLE_IMAGES))
    assert parser.format_id == "formetric-pdf-protocol-v1"
    result = results[0]
    assert result.params["DYN_PELVIC_OBLIQUITY"] == 17.0
    assert result.params["DYN_PELVIC_ROTATION"] == 5.0

    kinds = [f.kind for f in result.figures]
    assert kinds == ["render", "render", "caption"]        # логотип отброшен
    assert all(f.data.startswith(b"\xff\xd8") for f in result.figures)
    # Подпись есть → значения с иллюстрации в текстовый слой не попали.
    assert "figure_values_not_in_text_layer" in result.quality_flags


def test_figures_survive_a_broken_page():
    """Битое вложение не должно уносить с собой таблицу параметров."""
    from importers import parse_blob

    blob = bytearray(build_pdf(SAMPLE_IMAGES))
    idx = blob.find(b"/Subtype /Image")
    blob[idx:idx + 15] = b"/Subtype /Bogus"
    _, results = parse_blob(bytes(blob))
    assert results[0].params["DYN_PELVIC_OBLIQUITY"] == 17.0


@pytest_asyncio.fixture
async def client(monkeypatch):
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    monkeypatch.setenv("DIERS_DATABASE_URL", f"sqlite+aiosqlite:///{tmp.name}")
    import apps.api.db as db_mod
    import apps.api.settings as settings_mod
    settings_mod.get_settings.cache_clear()
    db_mod._engine = None
    db_mod._sessionmaker = None

    from httpx import ASGITransport, AsyncClient

    from apps.api.main import app
    from apps.api.models import Base

    async with db_mod.engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


OPER = {"X-Actor-Ref": "o1", "X-Actor-Role": "operator"}
SESSION = {
    "patient_ref": "pref-fig123def456", "neutral_definition": "habitual_occlusion",
    "informed_consent_ref": "ids-1", "operator_ref": "o1", "study_mode": False, "lld_mm": 0.0,
}


async def _approve_plan(client, session_id: str):
    """Утверждённый план — предусловие любой пробы (Р-29)."""
    return await client.post(f"/sessions/{session_id}/plan", headers=OPER, json={
        "probes": [
            {"probe_code": "MAND_NEUTRAL_WITH_APPARATUS", "position": 0},
            {"probe_code": "MAND_CLENCH", "position": 1},
            {"probe_code": "MAND_NEUTRAL_WITH_APPARATUS", "position": 2},
            {"probe_code": "MAND_NEUTRAL_WITH_APPARATUS", "position": 3},
        ],
        "apply_randomization": False,
    })


@pytest.mark.asyncio
async def test_uploaded_pdf_exposes_figures(client):
    """Сквозь весь путь: загрузка PDF → хранение → выдача с data:-URI."""
    s = (await client.post("/sessions", json=SESSION, headers=OPER)).json()
    plan = await _approve_plan(client, s["id"])
    assert plan.status_code == 200, plan.text
    made = await client.post(f"/sessions/{s['id']}/trials", headers=OPER, json={
        "probe_code": "MAND_CLENCH", "role": "diagnostic", "mode": "dynamic",
        "position": 1, "t_offset_sec": 120.0, "settle_sec_actual": 60,
        "effort_achieved_pct": 80.0,
    })
    assert made.status_code == 201, made.text
    trial = made.json()

    r = await client.post(
        f"/sessions/{s['id']}/imports?trial_id={trial['id']}", headers=OPER,
        files={"file": ("protocol.pdf", build_pdf(SAMPLE_IMAGES), "application/pdf")},
    )
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "parsed"

    got = (await client.get(f"/sessions/{s['id']}/figures", headers=OPER)).json()
    assert len(got["figures"]) == 3
    first = got["figures"][0]
    assert first["probe_code"] == "MAND_CLENCH"
    assert first["data_uri"].startswith("data:image/jpeg;base64,")

    raw = await client.get(first["url"], headers=OPER)
    assert raw.status_code == 200
    assert raw.content.startswith(b"\xff\xd8")
    assert "immutable" in raw.headers["cache-control"]


@pytest.mark.asyncio
async def test_manual_upload_refuses_multi_section_file(client):
    """QA (Р-43): ручная загрузка привязывает файл к ОДНОЙ пробе.

    Многораздельный отчёт сюда класть нельзя: разделы сняты при разных
    условиях, и сложенные в одну пробу они смешаются молча. Отказ с причиной
    лучше правдоподобного результата.
    """
    one = (
        "Parameter_F4_Dynamic4D - 04.03.2025 (18:27)\n"
        "лев окк\n"
        "ПАРАМЕТР ЗНАЧЕНИЕ ДИАПАЗОН ДВИЖЕНИЯ\n"
        "Ротация таза 5° Прав. 1° Лев. - 7° Прав.\n"
    )
    two = one.replace("лев окк", "прав окк").replace("Ротация таза 5°", "Ротация таза 9°")

    s = (await client.post("/sessions", json=SESSION, headers=OPER)).json()
    plan = await _approve_plan(client, s["id"])
    assert plan.status_code == 200, plan.text
    made = await client.post(f"/sessions/{s['id']}/trials", headers=OPER, json={
        "probe_code": "MAND_CLENCH", "role": "diagnostic", "mode": "dynamic",
        "position": 1, "t_offset_sec": 120.0, "settle_sec_actual": 60,
        "effort_achieved_pct": 80.0,
    })
    assert made.status_code == 201, made.text
    trial = made.json()
    r = await client.post(
        f"/sessions/{s['id']}/imports?trial_id={trial['id']}", headers=OPER,
        files={"file": ("protocol.txt", (one + "\n" + two).encode(), "text/plain")},
    )
    assert r.status_code == 409, r.text
    assert "разделов" in r.json()["detail"]


@pytest.mark.asyncio
async def test_broken_pdf_reports_a_human_reason(client):
    """Недокачанный отчёт — частый случай; «PdfStreamError» оператору не адресат."""
    s = (await client.post("/sessions", json=SESSION, headers=OPER)).json()
    assert (await _approve_plan(client, s["id"])).status_code == 200
    broken = build_pdf(SAMPLE_IMAGES)[:1500]
    r = await client.post(f"/sessions/{s['id']}/auto-ingest", headers=OPER,
                          files={"files": ("broken.pdf", broken, "application/pdf")})
    assert r.status_code == 200
    outcome = r.json()["files"][0]
    assert outcome["status"] in ("failed", "unrecognized")
    if outcome["status"] == "failed":
        assert "повреждён" in outcome["reason"]


@pytest.mark.asyncio
async def test_filename_never_reaches_the_audit_log(client):
    """Р-9: клиника называет выгрузки по пациенту — ПДн не должны осесть в журнале."""
    from sqlalchemy import select

    import apps.api.db as db_mod
    from apps.api.models import AuditLog

    s = (await client.post("/sessions", json=SESSION, headers=OPER)).json()
    assert (await _approve_plan(client, s["id"])).status_code == 200
    made = await client.post(f"/sessions/{s['id']}/trials", headers=OPER, json={
        "probe_code": "MAND_CLENCH", "role": "diagnostic", "mode": "static",
        "position": 1, "t_offset_sec": 120.0, "settle_sec_actual": 60,
        "effort_achieved_pct": 80.0,
    })
    assert made.status_code == 201, made.text
    trial = made.json()
    await client.post(
        f"/sessions/{s['id']}/imports?trial_id={trial['id']}", headers=OPER,
        files={"file": ("Петрова Жанна.csv", "ерунда;не формат\n1;2\n".encode(), "text/csv")},
    )
    async with db_mod.sessionmaker()() as db:
        rows = (await db.execute(select(AuditLog))).scalars().all()
    dump = repr([r.payload for r in rows])
    assert "Петрова" not in dump
    assert any("suffix" in (r.payload or {}) for r in rows)


def test_structures_are_read_from_the_printed_heading():
    """Р-47: структура берётся из заголовка листа, а не из пикселей.

    Прибор сам называет, о чём страница. Угадывать по виду картинки нельзя:
    в отчёте догадка была бы неотличима от факта.
    """
    from importers.formetric_pdf import structures_in

    assert structures_in("ПОДОГРАФИЯ · распределение нагрузки по стопам") == ("feet",)
    assert "pelvis" in structures_in("Ротация таза 5° Прав.")
    assert "knee" in structures_in("Ось ног: варус / вальгус")
    assert structures_in("СКОРОСТЬ 3 km/h") == ()          # структура не названа


def test_figures_carry_page_and_structures():
    """Иллюстрация помнит, с какой страницы взята и о чём та страница."""
    from importers import parse_blob

    _, results = parse_blob(build_pdf(SAMPLE_IMAGES))
    figures = results[0].figures
    assert figures
    assert all(f.page == 0 for f in figures)
    # Текст синтетического листа говорит о тазе — значит, и иллюстрации о нём.
    assert all("pelvis" in f.structures for f in figures)
