"""Канал беспроводных датчиков и приём снимков экрана (Р-44)."""
import io
import math
import os
import tempfile

import pytest
import pytest_asyncio

os.environ.setdefault("DIERS_DATABASE_URL", "")

FS = 2000.0
N = 4000


def _tone(freq: float, amp: float, offset: float = 0.0, n: int = N) -> list[float]:
    return [amp * math.sin(2 * math.pi * freq * i / FS) + offset for i in range(n)]


def _amp_at(xs: list[float], f: float) -> float:
    re = sum(x * math.cos(2 * math.pi * f * i / FS) for i, x in enumerate(xs))
    im = sum(x * math.sin(2 * math.pi * f * i / FS) for i, x in enumerate(xs))
    return math.hypot(re, im) / len(xs)


def test_mains_is_suppressed_and_emg_band_survives():
    """§9.8: сеть 50 Гц подавляется, полоса ЭМГ остаётся.

    Проверка не декоративная: фильтр, который «на глаз работает», может съесть
    рабочую полосу вместе с наводкой, и тогда все амплитуды окажутся ниже
    настоящих — систематически и незаметно.
    """
    from domain.emg_stream import bandpass, notch_mains, remove_dc

    raw = [a + b for a, b in zip(_tone(120, 50), _tone(50, 200, offset=500), strict=True)]
    out = notch_mains(bandpass(remove_dc(raw), FS), FS)
    assert _amp_at(out, 50) < 0.2 * _amp_at(raw, 50)      # наводка ослаблена ≥5 раз
    assert _amp_at(out, 120) > 0.9 * _amp_at(raw, 120)    # полоса ЭМГ цела


def test_dc_offset_does_not_leak_into_rms():
    """Смещение усилителя иначе выглядит как активность покоящейся мышцы."""
    from domain.emg_stream import process_capture

    quiet = process_capture({"CH1": [500.0] * N}, FS).channels[0]
    assert quiet.rms_uv < 1.0


def test_low_sample_rate_is_refused_not_silently_narrowed():
    """Полоса до 450 Гц требует более 900 Гц. Молча сузить полосу нельзя:
    это изменило бы метод, оставив прежнее название."""
    from domain.emg_stream import StreamError, process_capture

    with pytest.raises(StreamError, match="дискретизации"):
        process_capture({"CH1": _tone(100, 10, n=800)}, 800.0)


def test_snr_needs_a_rest_epoch():
    """Без записанного покоя SNR §9.8 не определён — и так и сказано.

    Оценка по самой активной записи измеряла бы долю отфильтрованного, то есть
    свойство фильтра, а не канала.
    """
    from domain.emg_stream import process_capture

    active = {
        "CH1": [a + b for a, b in zip(_tone(120, 50), _tone(50, 20, offset=500), strict=True)]}
    rest = {"CH1": [a + b for a, b in zip(_tone(120, 5), _tone(50, 20, offset=500), strict=True)]}

    without = process_capture(active, FS).channels[0]
    assert without.snr_db is None
    assert "snr_not_assessable" in without.flags

    with_rest = process_capture(active, FS, rest=rest).channels[0]
    assert with_rest.snr_db is not None and with_rest.snr_db > 10


def test_packet_loss_and_actual_rate_are_flagged_not_hidden():
    """Беспроводной канал теряет пакеты. Пересчёт скрыл бы рваную запись."""
    from domain.emg_stream import process_capture

    ts = [i * 1000 / FS for i in range(N)]
    for i in (1000, 2000):
        ts[i:] = [x + 50 for x in ts[i:]]                 # два провала по 50 мс
    r = process_capture({"CH1": _tone(120, 40)}, FS, timestamps_ms=ts)
    assert any(f.startswith("packet_loss:2") for f in r.flags)
    # Два коротких провала на две секунды записи почти не смещают среднюю
    # частоту — и флага о частоте здесь быть НЕ должно: он о другом отказе.
    assert r.fs_actual is not None and r.fs_actual < FS
    assert not any(f.startswith("resample_suspected") for f in r.flags)

    # Прибор писал вдвое медленнее заявленного — это уже расхождение частоты.
    slow = process_capture({"CH1": _tone(120, 40)}, FS,
                           timestamps_ms=[i * 2000 / FS for i in range(N)])
    assert any(f.startswith("resample_suspected:") for f in slow.flags)


def test_channels_without_montage_do_not_become_params():
    """Р-42: канал без прописи в параметры не идёт, но и не теряется."""
    from domain.emg_stream import process_capture

    r = process_capture({"CH1": _tone(120, 40), "CH9": _tone(120, 30)}, FS)
    params = r.params({"ch1": ("MASSETER", "L")})
    assert set(params) == {"EMG_RMS_MASSETER_L"}
    assert r.unmapped_labels({"ch1": ("MASSETER", "L")}) == ["CH9"]


def test_unverified_profile_is_declared_as_such():
    """Ошибка в коэффициенте к мкВ даёт правдоподобные, но неверные амплитуды."""
    from domain.config import load_ble_profiles

    lib = load_ble_profiles()
    assert lib.profiles
    for p in lib.profiles:
        assert p.verified is False                        # железа для сверки нет
        assert p.unit_scale_uv > 0
        assert len(p.channel_order) == p.channels_per_packet


# ── Снимки экрана ────────────────────────────────────────────────────────────

def _png(size: tuple[int, int], colour: tuple[int, int, int]) -> bytes:
    Image = pytest.importorskip("PIL.Image")
    buf = io.BytesIO()
    Image.new("RGB", size, colour).save(buf, "PNG")
    return buf.getvalue()


def test_screenshot_is_kept_as_evidence_without_values():
    """Р-44: снимок принимается картинкой, чисел из растра не появляется.

    Числа со снимка вводит человек: у величины из растра нет прослеживаемого
    источника (§5.2а), а ошибка распознавания даёт правдоподобное измерение,
    которого никто не делал.
    """
    from importers import parse_blob

    parser, results = parse_blob(_png((1600, 900), (18, 20, 28)))
    assert parser.format_id == "device-screenshot-v1"
    r = results[0]
    assert r.params == {}
    assert len(r.figures) == 1 and r.figures[0].mime == "image/png"
    assert "screenshot_values_require_manual_entry" in r.quality_flags
    assert r.raw_row["screen_kind"] == "trace"            # тёмный широкий — развёртка


def test_screen_kind_separates_trace_from_report():
    from importers.screenshot import classify_screen

    assert classify_screen(1600, 900, 0.8) == "trace"
    assert classify_screen(1200, 1000, 0.05) == "report"
    assert classify_screen(400, 1400, 0.9) == "unknown"    # ни то, ни другое


def test_tiny_image_is_not_a_screenshot():
    """Значок или обрезок снимком экрана прибора не является."""
    from importers import ParserNotFound, parse_blob

    with pytest.raises((ValueError, ParserNotFound)):
        parse_blob(_png((100, 80), (0, 0, 0)))


# ── API ──────────────────────────────────────────────────────────────────────

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
    "patient_ref": "pref-dev123def456", "neutral_definition": "habitual_occlusion",
    "informed_consent_ref": "ids-1", "operator_ref": "o1", "study_mode": False, "lld_mm": 0.0,
}


async def _prepared(client):
    s = (await client.post("/sessions", json=SESSION, headers=OPER)).json()
    plan = await client.post(f"/sessions/{s['id']}/plan", headers=OPER, json={
        "probes": [
            {"probe_code": "MAND_NEUTRAL_WITH_APPARATUS", "position": 0},
            {"probe_code": "MAND_CLENCH", "position": 1},
            {"probe_code": "MAND_NEUTRAL_WITH_APPARATUS", "position": 2},
            {"probe_code": "MAND_NEUTRAL_WITH_APPARATUS", "position": 3},
        ],
        "apply_randomization": False,
    })
    assert plan.status_code == 200, plan.text
    trial = await client.post(f"/sessions/{s['id']}/trials", headers=OPER, json={
        "probe_code": "MAND_CLENCH", "role": "diagnostic", "mode": "static",
        "position": 1, "t_offset_sec": 120.0, "settle_sec_actual": 60,
        "effort_achieved_pct": 80.0,
    })
    assert trial.status_code == 201, trial.text
    return s["id"], trial.json()["id"]


@pytest.mark.asyncio
async def test_ble_capture_writes_params_through_the_montage(client):
    sid, tid = await _prepared(client)
    await client.put(f"/sessions/{sid}/montage", headers=OPER, json={
        "channels": [{"label": "CH1", "muscle": "MASSETER", "side": "L"},
                     {"label": "CH2", "muscle": "MASSETER", "side": "R"}],
    })
    r = await client.post(f"/sessions/{sid}/ble-capture", headers=OPER, json={
        "trial_id": tid, "profile": "BLE_HRS_LIKE_4CH",
        "channels": {"CH1": _tone(120, 200), "CH2": _tone(120, 260), "CH7": _tone(120, 90)},
        "timestamps_ms": [i * 1000 / FS for i in range(N)],
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "captured"
    assert "EMG_RMS_MASSETER_L" in body["params"]
    assert "EMG_ASYM_MASSETER" in body["params"]
    # Профиль не проверен на железе — запись об этом остаётся при данных.
    assert "ble_profile_unverified" in body["quality_flags"]
    # Канал без прописи не потерян и не превращён в параметр.
    assert body["unmapped"] == ["CH7"]
    assert any(f.startswith("channels_without_montage:") for f in body["quality_flags"])

    again = await client.post(f"/sessions/{sid}/ble-capture", headers=OPER, json={
        "trial_id": tid, "profile": "BLE_HRS_LIKE_4CH",
        "channels": {"CH1": _tone(120, 200), "CH2": _tone(120, 260), "CH7": _tone(120, 90)},
        "timestamps_ms": [i * 1000 / FS for i in range(N)],
    })
    assert again.json()["status"] == "duplicate"           # §4 инвариант 1


@pytest.mark.asyncio
async def test_screenshot_upload_is_stored_as_a_figure(client):
    sid, tid = await _prepared(client)
    r = await client.post(f"/sessions/{sid}/imports?trial_id={tid}", headers=OPER,
                          files={"file": ("экран.png", _png((1600, 900), (18, 20, 28)),
                                          "image/png")})
    assert r.status_code == 201, r.text
    figures = (await client.get(f"/sessions/{sid}/figures", headers=OPER)).json()
    assert len(figures["figures"]) == 1
    assert figures["figures"][0]["probe_code"] == "MAND_CLENCH"


@pytest.mark.asyncio
async def test_custom_montage_template_roundtrip(client):
    """Р-45: свой шаблон собирается из групп мышц и применяется как поставляемый."""
    created = await client.post("/emg/montages", headers=OPER, json={
        "code": "MY_PELVIS", "label_ru": "Моя тазовая", "purpose": "клин под пятку",
        "channels": [{"muscle": "GLUTEUS_MAXIMUS", "side": "both"},
                     {"muscle": "GLUTEUS_MEDIUS", "side": "both"},
                     {"muscle": "SOLEUS", "side": "L"}],
    })
    assert created.status_code == 201, created.text
    tpl = created.json()["template"]
    assert tpl["channel_count"] == 5                        # 2+2+1
    assert tpl["builtin"] is False
    assert created.json()["warnings"]                       # SOLEUS с одной стороны

    listed = (await client.get("/emg/montages", headers=OPER)).json()["montages"]
    assert any(m["code"] == "MY_PELVIS" and m["builtin"] is False for m in listed)
    assert any(m["code"] == "TMJ_PANEL" and m["builtin"] is True for m in listed)

    sid, _ = await _prepared(client)
    applied = await client.put(f"/sessions/{sid}/montage", headers=OPER,
                               json={"template": "MY_PELVIS"})
    assert applied.status_code == 200, applied.text
    assert len(applied.json()["montage"]["channels"]) == 5

    dropped = await client.delete("/emg/montages/MY_PELVIS", headers=OPER)
    assert dropped.status_code == 200
    after = (await client.get("/emg/montages", headers=OPER)).json()["montages"]
    assert not any(m["code"] == "MY_PELVIS" for m in after)


@pytest.mark.asyncio
async def test_builtin_template_code_cannot_be_shadowed(client):
    """Подмена состава поставляемого шаблона объявила бы прошлые сессии
    записанными не тем."""
    r = await client.post("/emg/montages", headers=OPER, json={
        "code": "TMJ_PANEL", "label_ru": "Подмена",
        "channels": [{"muscle": "MASSETER", "side": "both"}],
    })
    assert r.status_code == 409
    assert "занят" in r.json()["detail"]


# ── Печатный отчёт myoline (Р-48) ────────────────────────────────────────────

MYOLINE_TEXT = (
    "Область норматив.знач.\n"
    "ТУЛОВИЩЕ\n"
    "Туловище| Разгибание / Сгибание\n"
    "Разгибание 252 N / 78%\n"
    "Сгибание 126 N / 100%\n"
    "Туловище| Наклон налево / Наклон направо\n"
    "Наклон налево 199 N / 72%\n"
    "Наклон направо 276 N / 100%\n"
    "ШЕЙНЫЙ ОТДЕЛ\n"
    "Шейный отдел| Сгибание / Разгибание\n"
    "Сгибание 78 N / 100%\n"
    "Разгибание 73 N / 94%\n"
    "последовательность Из 04.06.2025 | нейтр\n"
    "Имя: Иванов Иван Иванович (* 01.01.1990)\n"
    "Comparison Agonist/AntagonistВерсия ПО 3.24.1.7\n"
)


def _myoline_pdf() -> bytes:
    """Синтетический лист с той же раскладкой. Настоящий отчёт в репозиторий
    не кладётся: его текстовый слой несёт ФИО и дату рождения (Р-9)."""
    from tests.test_figures import build_pdf_with_text

    return build_pdf_with_text(MYOLINE_TEXT, [("Pic1", 129, 129), ("Bar", 300, 2)])


def test_myoline_report_is_parsed_by_pairs():
    """Значения привязываются по ИМЕНИ движения, а не по порядку строк.

    Смена порядка в другой версии печати иначе переставила бы стороны местами,
    и левое стало бы правым — ошибка, неотличимая от биологии.
    """
    from importers import parse_blob

    parser, results = parse_blob(_myoline_pdf())
    assert parser.format_id == "myoline-pdf-agonist-v1"
    p = results[0].params
    assert p["MYO_FORCE_TRUNK_EXT"] == 252.0
    assert p["MYO_FORCE_TRUNK_FLEX"] == 126.0
    assert p["MYO_FORCE_TRUNK_LAT_L"] == 199.0
    assert p["MYO_FORCE_TRUNK_LAT_R"] == 276.0
    assert p["MYO_FORCE_CERVICAL_FLEX"] == 78.0
    assert p["MYO_FORCE_CERVICAL_EXT"] == 73.0
    assert results[0].raw_row["condition_label"] == "нейтр"
    assert results[0].device_sw_version == "3.24.1.7"


def test_device_percent_is_kept_apart_from_platform_norms():
    """«252 N / 78%» — процент норматива ПРИБОРА. Наши нормы пусты (Р-13), и
    подставить чужую шкалу на их место значило бы считать «отклонение от нормы»
    по величине, которую мы не проверяли."""
    from importers import parse_blob

    _, results = parse_blob(_myoline_pdf())
    p = results[0].params
    assert p["MYO_PCT_TRUNK_EXT"] == 78.0
    assert "device_normative_percent_not_platform_norms" in results[0].quality_flags


def test_agonist_ratio_is_computed_from_forces_not_percents():
    """Отношение процентов измеряло бы шкалу прибора, а не пациента."""
    from importers import parse_blob

    _, results = parse_blob(_myoline_pdf())
    p = results[0].params
    assert p["MYO_RATIO_TRUNK_EXT_FLEX"] == round(252.0 / 126.0, 3)
    assert p["MYO_ASYM_TRUNK_LAT"] == round(200 * (276 - 199) / (276 + 199), 2)


def test_patient_name_never_enters_the_parse():
    """Р-9: отчёт печатает ФИО и дату рождения — в модуль они не попадают,
    в том числе в `unmapped` под видом неканонической строки."""
    from importers import parse_blob

    _, results = parse_blob(_myoline_pdf())
    dump = repr(results[0].params) + repr(results[0].unmapped) + repr(results[0].raw_row)
    assert "Иванов" not in dump
    assert "1990" not in dump


def test_formetric_parser_no_longer_grabs_every_pdf():
    """Прежняя редакция забирала любой PDF, и отчёт myoline падал у неё вместо
    того, чтобы достаться своему парсеру."""
    from importers.formetric_pdf import FormetricPdfProtocolParser

    assert FormetricPdfProtocolParser().detect(_myoline_pdf()) is False
