"""Сквозные проверки приёмки (§16 ТЗ): регуляторные предохранители, слепота,
идемпотентность, детерминизм, сопоставимость визитов."""
import json
import os
import tempfile

import pytest
import pytest_asyncio

os.environ.setdefault("DIERS_DATABASE_URL", "")


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


CLIN = {"X-Actor-Ref": "c1", "X-Actor-Role": "clinician"}
OPER = {"X-Actor-Ref": "o1", "X-Actor-Role": "operator"}
METH = {"X-Actor-Ref": "m1", "X-Actor-Role": "methodologist"}

SESSION = {
    "patient_ref": "pref-abc123def456", "neutral_definition": "habitual_occlusion",
    "informed_consent_ref": "ids-1", "operator_ref": "o1", "study_mode": False, "lld_mm": 3.0,
}


@pytest.mark.asyncio
async def test_platform_reports_demo_thresholds(client):
    r = await client.get("/platform")
    assert r.status_code == 200
    body = r.json()
    assert body["thresholds_are_demo"] is True
    assert body["norms_defined"] is False
    assert any("некалиброван" in b for b in body["banners"])


@pytest.mark.asyncio
async def test_session_requires_informed_consent(client):
    """Р-24: без ИДС сессия НЕ СОЗДАЁТСЯ — согласие предшествует вмешательству."""
    bad = {**SESSION, "informed_consent_ref": ""}
    assert (await client.post("/sessions", json=bad, headers=OPER)).status_code == 422


@pytest.mark.asyncio
async def test_research_session_requires_separate_consent(client):
    bad = {**SESSION, "study_mode": True}
    r = await client.post("/sessions", json=bad, headers=OPER)
    assert r.status_code == 422
    assert "исследовани" in r.json()["detail"]


@pytest.mark.asyncio
async def test_enumerable_patient_ref_rejected(client):
    """Р-9: последовательный идентификатор хоста обезличиванием не является."""
    bad = {**SESSION, "patient_ref": "1000042"}
    assert (await client.post("/sessions", json=bad, headers=OPER)).status_code == 422


@pytest.mark.asyncio
async def test_no_trials_before_plan_approval(client):
    """Р-29: до утверждения плана не выполняется ни одна проба."""
    s = (await client.post("/sessions", json=SESSION, headers=OPER)).json()
    r = await client.post(f"/sessions/{s['id']}/trials", headers=OPER, json={
        "probe_code": "MAND_CLENCH", "role": "diagnostic", "position": 0,
        "t_offset_sec": 0, "settle_sec_actual": 999,
    })
    assert r.status_code == 409
    assert "план не утверждён" in r.json()["detail"]


@pytest.mark.asyncio
async def test_plan_validators_block_before_first_probe(client):
    """Р-31: проверки полноты — до первой пробы, а не когда пациент ушёл."""
    s = (await client.post("/sessions", json=SESSION, headers=OPER)).json()
    r = await client.post(f"/sessions/{s['id']}/plan", headers=OPER, json={
        "probes": [{"probe_code": "MAND_CLENCH", "position": 0}], "apply_randomization": False,
    })
    assert r.status_code == 422
    codes = {v["code"] for v in r.json()["detail"]["violations"]}
    assert "neutral_count" in codes


@pytest.mark.asyncio
async def test_quality_screen_is_blind(client):
    """Р-17: экран разбора не отдаёт код пробы, роль и порядковый номер."""
    s = (await client.post("/sessions", json=SESSION, headers=OPER)).json()
    r = await client.get(f"/sessions/{s['id']}/quality", headers=CLIN)
    assert r.status_code == 200
    for item in r.json():
        assert set(item) == {"measurement_id", "modality", "quality_flags", "param_count"}


@pytest.mark.asyncio
async def test_coach_and_patient_variants_blocked_in_research(client):
    """Р-33: оба варианта содержат предписания, режим research их не выпускает."""
    from apps.api.security import RESEARCH_FORBIDDEN_VARIANTS
    assert {"patient", "coach"} == RESEARCH_FORBIDDEN_VARIANTS


@pytest.mark.asyncio
async def test_operator_cannot_get_reports(client):
    from apps.api.security import REPORT_MATRIX
    assert REPORT_MATRIX["operator"] == frozenset()


@pytest.mark.asyncio
async def test_history_reports_incomparable_without_analyses(client):
    await client.post("/sessions", json=SESSION, headers=OPER)
    r = await client.get(f"/patients/{SESSION['patient_ref']}/history", headers=CLIN)
    assert r.json()["comparable"] is False


@pytest.mark.asyncio
async def test_clinical_mode_requires_registration_number(monkeypatch):
    """Р-25: сборка не стартует в clinical без РУ — эксплуатация без него запрещена."""
    from apps.api.settings import Settings
    with pytest.raises(Exception) as e:
        Settings(intended_use="clinical", registration_number=None)
    assert "РУ" in str(e.value) or "REGISTRATION" in str(e.value)


@pytest.mark.asyncio
async def test_external_llm_endpoint_rejected():
    """Р-23: отправка во внешний сервис — трансграничная передача (ФЗ-152 ст. 12)."""
    from apps.api.settings import Settings
    with pytest.raises(Exception) as e:
        Settings(llm_endpoint="https://api.openai.com/v1")
    assert "трансграничная" in str(e.value)


@pytest.mark.asyncio
async def test_concurrent_analyze_returns_stored_analysis_not_500(client):
    """Р-34 под гонкой: одновременный анализ отдаёт сохранённый, а не пятисотку.

    Проверка «записи ещё нет» и вставка не атомарны, и окно между ними реально:
    два окна врача, повтор после таймаута, автопереанализ рядом с ручным. В это
    окно чужой запрос успевает сохранить анализ С ТЕМ ЖЕ input_hash;
    уникальность (session_id, input_hash) срабатывает как задумано, и вопрос
    лишь в том, что увидит клиент — сохранённый анализ или ошибку сервера.

    Гонка воспроизводится ПРИЦЕЛЬНО: конкурирующая строка пишется отдельным
    соединением ровно между выборкой и вставкой. Вариант «запустим два запроса
    и понадеемся» такой дефект пропускает — он и пропускал, пока сюда не
    поставили точную врезку.
    """
    import os
    import sqlite3
    from uuid import uuid4

    from apps.api.routers import analyses as mod
    from apps.api.seed import seed
    await seed(1)

    sid = (await client.get("/sessions", headers=CLIN)).json()[0]["id"]
    first = await client.post(f"/sessions/{sid}/analyze", json={}, headers=CLIN)
    assert first.status_code == 200, first.text
    stored = first.json()

    path = os.environ["DIERS_DATABASE_URL"].split("///", 1)[1]
    with sqlite3.connect(path) as conn:                     # чистим сохранённое,
        conn.execute("DELETE FROM analyses WHERE session_id = ?", (sid,))  # чтобы
                                                            # запрос пошёл по ветке вставки
    real_run = mod.run_analysis

    class Racing:
        """Обёртка результата: конкурирующая запись делается в `to_dict()`.

        Это единственный вызов между выборкой «записи нет» и вставкой — то
        самое окно. Подменять сам `Analysis` нельзя: его же имя стоит в
        `select(Analysis)`, и подмена сломала бы выборку вместо гонки.
        """

        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

        def to_dict(self):
            payload = self._inner.to_dict()
            with sqlite3.connect(path) as conn:
                conn.execute(
                    "INSERT INTO analyses (id, session_id, norms_version,"
                    " thresholds_version, rules_version, profile_version,"
                    " registry_version, input_hash, index_kind, result, created_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,datetime('now'))",
                    (str(uuid4()), sid, *[self._inner.versions[k] for k in (
                        "norms_version", "thresholds_version", "rules_version",
                        "profile_version", "registry_version")],
                     self._inner.input_hash, self._inner.index_kind,
                     json.dumps(payload, ensure_ascii=False)),
                )
            return payload

    mod.run_analysis = lambda *a, **kw: Racing(real_run(*a, **kw))   # type: ignore[assignment]
    try:
        second = await client.post(f"/sessions/{sid}/analyze", json={}, headers=CLIN)
    finally:
        mod.run_analysis = real_run                                 # type: ignore[assignment]

    assert second.status_code == 200, second.text
    assert second.json()["input_hash"] == stored["input_hash"]


@pytest.mark.asyncio
async def test_gateway_token_required_when_configured(monkeypatch):
    """§15: с заданным секретом хоста вызов без него не принимается.

    Аутентификация пользователя вынесена за модуль — актор и роль приходят
    заголовками. Но ЧТО запрос пришёл от хоста, не проверялось ничем: кто
    дотянулся до порта, тот и объявлял себя `X-Actor-Role: admin`. Секрет
    закрывает дыру, не втаскивая в модуль пользовательскую аутентификацию.
    """
    import tempfile

    secret = "x" * 48
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    monkeypatch.setenv("DIERS_DATABASE_URL", f"sqlite+aiosqlite:///{tmp.name}")
    monkeypatch.setenv("DIERS_GATEWAY_TOKEN", secret)

    import apps.api.db as db_mod
    import apps.api.settings as settings_mod
    settings_mod.get_settings.cache_clear()
    db_mod._engine = None
    db_mod._sessionmaker = None

    import importlib

    from httpx import ASGITransport, AsyncClient

    import apps.api.main as main_mod
    importlib.reload(main_mod)
    from apps.api.models import Base
    async with db_mod.engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        async with AsyncClient(transport=ASGITransport(app=main_mod.app),
                               base_url="http://t") as c:
            assert (await c.get("/platform", headers=CLIN)).status_code == 401
            wrong = "y" * 48       # заголовки только ASCII — отсюда латиница
            assert (await c.get("/platform", headers={**CLIN, "X-Gateway-Token": wrong})
                    ).status_code == 401
            ok = await c.get("/platform", headers={**CLIN, "X-Gateway-Token": secret})
            assert ok.status_code == 200
            # Пробы живости отвечают без секрета: иначе оркестратор получал бы
            # 401 и перезапускал исправный контейнер по кругу.
            assert (await c.get("/health")).status_code == 200
    finally:
        monkeypatch.delenv("DIERS_GATEWAY_TOKEN", raising=False)
        settings_mod.get_settings.cache_clear()
        db_mod._engine = None
        db_mod._sessionmaker = None
        importlib.reload(main_mod)


@pytest.mark.asyncio
async def test_oversized_body_rejected_before_reading(client):
    """§5: тело больше предела отвергается по Content-Length, до чтения.

    Смысл предела в том, чтобы гигабайт не заезжал в процесс, а не в том, чтобы
    отвергнуть его после приёма.
    """
    from apps.api.settings import get_settings
    limit = get_settings().max_upload_mb * 1024 * 1024
    r = await client.post("/sessions", headers={**OPER, "Content-Length": str(limit + 1)},
                          content=b"{}")
    assert r.status_code == 413
    assert "МБ" in r.json()["detail"]


@pytest.mark.asyncio
async def test_clinical_mode_requires_gateway_token():
    """Р-25 + §15: клинический контур без проверки вызывающей стороны не стартует."""
    from apps.api.settings import Settings
    with pytest.raises(Exception) as e:
        Settings(intended_use="clinical", registration_number="РЗН-2026-1")
    assert "GATEWAY_TOKEN" in str(e.value)


@pytest.mark.asyncio
async def test_short_gateway_token_rejected():
    """Короткий секрет подбирается перебором — старт с ним запрещён."""
    from apps.api.settings import Settings
    with pytest.raises(Exception) as e:
        Settings(gateway_token="коротко")
    assert "32" in str(e.value)


@pytest.mark.asyncio
async def test_unprotected_contour_is_announced(client):
    """Без секрета платформа ГОВОРИТ, что контур открыт.

    Молчаливая незащищённость хуже отсутствия защиты: развернувший считает, что
    всё в порядке, потому что ничто не возразило.
    """
    banners = (await client.get("/platform")).json()["banners"]
    assert any("Контур не защищён" in b for b in banners)
