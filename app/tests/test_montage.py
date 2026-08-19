"""Каталог мышц, шаблоны и ручная пропись каналов ЭМГ (Р-42)."""
import os
import tempfile

import pytest
import pytest_asyncio

os.environ.setdefault("DIERS_DATABASE_URL", "")


def test_catalog_covers_all_regions_of_the_layout():
    """Каждая мышца каталога попадает в область обзора §14.3.

    Мышца без области выпала бы из таблицы «от сустава до стоп» молча —
    данные есть, показать их негде.
    """
    from domain.config import load_anatomy, load_muscles

    anatomy = load_anatomy()
    keys = {r.key for r in anatomy.regions}
    for m in load_muscles().muscles:
        assert m.region in keys, f"{m.code}: области {m.region} нет в раскладке"


def test_every_surface_muscle_has_registry_codes(bundle):
    """Каталог и реестр порождаются из одного источника и обязаны совпадать.

    Раньше алиасы жили в парсере, коды — в реестре, области — в раскладке;
    при каждом пополнении три списка расходились.
    """
    from domain.config import load_muscles

    for m in load_muscles().muscles:
        if not m.surface:
            assert bundle.registry.get(f"EMG_RMS_{m.code}_L") is None, (
                f"{m.code} не снимается поверхностно, но код в реестре есть")
            continue
        for side in ("L", "R"):
            assert bundle.registry.get(f"EMG_RMS_{m.code}_{side}") is not None, m.code
        assert bundle.registry.get(f"EMG_ASYM_{m.code}") is not None, m.code


def test_legacy_codes_survived_the_catalog(bundle):
    """Десять прежних кодов не переименованы: иначе загруженные сессии оказались
    бы измеренными «не тем»."""
    for code in ("MASSETER", "TEMPORALIS", "SCM", "TRAPEZIUS", "ERECTOR_SPINAE",
                 "QUADRATUS_LUMBORUM", "GLUTEUS_MAXIMUS", "RECTUS_FEMORIS",
                 "TIBIALIS_ANTERIOR", "GASTROCNEMIUS"):
        assert bundle.registry.get(f"EMG_RMS_{code}_L") is not None, code


def test_template_expands_to_channels():
    from domain.montage import from_template

    m = from_template("TMJ_PANEL")
    assert m.template == "TMJ_PANEL"
    assert len(m.channels) == 8                       # 4 мышцы × 2 стороны
    assert "EMG_ASYM_MASSETER" in m.param_codes()


def test_template_labels_can_be_overridden():
    """Миограф подписывает провода по-своему: монтаж должен это принимать."""
    from domain.montage import from_template

    m = from_template("TMJ_PANEL", labels={"MASSETER_L": "CH1", "MASSETER_R": "CH2"})
    assert m.channel_map()["ch1"] == ("MASSETER", "L")


def test_manual_channels_reject_deep_muscles():
    """Подписать канал глубокой мышцей значит объявить измеренным то, чего
    поверхностная ЭМГ не измеряет."""
    from domain.montage import MontageError, build_montage

    with pytest.raises(MontageError, match="поверхностн"):
        build_montage([{"label": "CH1", "muscle": "ILIOPSOAS", "side": "L"}])


def test_manual_channels_reject_duplicate_label():
    """Две мышцы на одну метку — при разборе одна запись перетёрла бы другую."""
    from domain.montage import MontageError, build_montage

    with pytest.raises(MontageError, match="дважды"):
        build_montage([
            {"label": "CH1", "muscle": "MASSETER", "side": "L"},
            {"label": "ch1", "muscle": "SCM", "side": "R"},
        ])


def test_one_sided_montage_is_allowed_but_warned():
    """Односторонний монтаж пишут осознанно; асимметрии по нему не будет, и
    узнать об этом лучше при настройке, чем при пустой колонке."""
    from domain.montage import build_montage

    m = build_montage([{"label": "CH1", "muscle": "SOLEUS", "side": "L"}])
    assert m.warnings and "асимметрия" in m.warnings[0]
    assert "EMG_ASYM_SOLEUS" not in m.param_codes()


def test_unnamed_channels_resolve_only_with_a_montage():
    """Главный случай: миограф подписал «CH1…CH4», и без прописи мышцу не
    восстановить ничем. Догадка здесь запрещена."""
    from domain.montage import from_template
    from importers.emg_csv import EmgCsvParser

    blob = "Condition;CH1;CH2;CH3;CH4\nлев окк;38,2;51,7;22,4;29,8\n".encode()
    parser = EmgCsvParser()
    assert parser.detect(blob) is False               # сам по себе не опознаётся

    montage = from_template("TMJ_PANEL", labels={
        "MASSETER_L": "CH1", "MASSETER_R": "CH2",
        "TEMPORALIS_L": "CH3", "TEMPORALIS_R": "CH4"})
    cmap = montage.channel_map()
    assert parser.detect(blob, cmap) is True
    result = parser.parse(blob, cmap)[0]
    assert result.params["EMG_RMS_MASSETER_R"] == 51.7
    assert result.params["EMG_ASYM_TEMPORALIS"] == pytest.approx(28.35, abs=0.01)


def test_apply_montage_rescues_partially_named_files():
    """Часть каналов подписана понятно, часть — «CH7»: спасаем вторую половину."""
    from domain.montage import apply_montage, build_montage
    from importers import parse_blob

    blob = "Condition;MASS_L;MASS_R;CH7\nлев окк;38,2;51,7;12,5\n".encode()
    _, results = parse_blob(blob)
    assert "CH7" in results[0].unmapped                # §5.1: не потеряно молча

    montage = build_montage([{"label": "CH7", "muscle": "SCM", "side": "R"}])
    apply_montage(results[0], montage)
    assert results[0].params["EMG_RMS_SCM_R"] == 12.5
    assert "CH7" not in results[0].unmapped        # разобран, а не потерян
    assert "channels_from_montage:1" in results[0].quality_flags


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
    "patient_ref": "pref-mnt123def456", "neutral_definition": "habitual_occlusion",
    "informed_consent_ref": "ids-1", "operator_ref": "o1", "study_mode": False, "lld_mm": 0.0,
}


@pytest.mark.asyncio
async def test_catalog_and_templates_are_served(client):
    muscles = (await client.get("/emg/muscles", headers=OPER)).json()
    assert len(muscles["muscles"]) > 30
    deep = [m for m in muscles["muscles"] if not m["surface"]]
    assert deep and all(m["note"] for m in deep)      # сказано, почему нельзя

    montages = (await client.get("/emg/montages", headers=OPER)).json()
    codes = {m["code"] for m in montages["montages"]}
    assert {"TMJ_PANEL", "POSTURAL_FULL", "SHANK_FOOT"} <= codes


@pytest.mark.asyncio
async def test_session_montage_roundtrip_and_ingest(client):
    """Пропись каналов делает читаемым файл, который иначе не опознаётся."""
    s = (await client.post("/sessions", json=SESSION, headers=OPER)).json()
    empty = (await client.get(f"/sessions/{s['id']}/montage", headers=OPER)).json()
    assert empty["montage"] is None

    r = await client.put(f"/sessions/{s['id']}/montage", headers=OPER, json={
        "template": "TMJ_PANEL",
        "channels": [
            {"label": "CH1", "muscle": "MASSETER", "side": "L"},
            {"label": "CH2", "muscle": "MASSETER", "side": "R"},
            {"label": "CH3", "muscle": "SCM", "side": "L"},
            {"label": "CH4", "muscle": "SCM", "side": "R"},
        ],
        "note": "запись 12.05, электроды по SENIAM",
    })
    assert r.status_code == 200, r.text
    assert len(r.json()["montage"]["channels"]) == 4

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
    blob = "Condition;CH1;CH2;CH3;CH4\nсжатие зубов;38,2;51,7;22,4;29,8\n".encode()
    got = await client.post(f"/sessions/{s['id']}/auto-ingest", headers=OPER,
                            files={"files": ("emg.csv", blob, "text/csv")})
    assert got.status_code == 200, got.text
    outcome = got.json()["files"][0]
    assert outcome["status"] == "ingested", outcome
    assert outcome["modality"] == "emg"
    assert outcome["params"] >= 4


@pytest.mark.asyncio
async def test_invalid_montage_is_refused_with_a_reason(client):
    s = (await client.post("/sessions", json=SESSION, headers=OPER)).json()
    r = await client.put(f"/sessions/{s['id']}/montage", headers=OPER, json={
        "channels": [{"label": "CH1", "muscle": "TRANSVERSUS_ABDOMINIS", "side": "L"}],
    })
    assert r.status_code == 422
    assert "поверхностн" in r.json()["detail"]
