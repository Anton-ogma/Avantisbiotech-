from __future__ import annotations

import logging
import sys
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

PACKAGES = Path(__file__).resolve().parents[2] / "packages"
if str(PACKAGES) not in sys.path:
    sys.path.insert(0, str(PACKAGES))

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .db import engine
from .models import Base
from .routers import analyses, crossmodal, imports, ingest, meta, research, sessions
from .services.bundle import bundle_from_settings
from .settings import get_settings

log = logging.getLogger("diers")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    # MUST §10: невалидная конфигурация РОНЯЕТ ЗАПУСК, а не деградирует молча.
    bundle = bundle_from_settings(s)
    log.info("режим=%s версии=%s", s.intended_use, bundle.versions)
    for banner in s.banners:
        log.warning("БАННЕР: %s", banner)
    if s.database_url.startswith("sqlite"):
        async with engine().begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    yield
    await engine().dispose()


app = FastAPI(
    title="DIERS — постуральный модуль",
    description=(
        "Научно-практическая платформа: выявляет закономерности, а не применяет готовые. "
        "Реализация по ТЗ v1.0 с решениями Р-1…Р-35."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

_settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    """Идентификатор запроса и время ответа — база наблюдаемости при горизонтальном
    масштабировании: без корреляции по request_id разбор инцидента на десятке
    инстансов невозможен."""
    request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:                                        # noqa: BLE001
        log.exception("request_id=%s необработанная ошибка", request_id)
        return JSONResponse({"detail": "внутренняя ошибка", "request_id": request_id},
                            status_code=500)
    response.headers["X-Request-Id"] = request_id
    response.headers["Server-Timing"] = f"app;dur={(time.perf_counter() - started) * 1000:.1f}"
    return response


@app.get("/health", tags=["meta"])
async def health() -> dict:
    return {"status": "ok"}


@app.get("/ready", tags=["meta"])
async def ready() -> dict:
    from sqlalchemy import text
    async with engine().connect() as conn:
        await conn.execute(text("SELECT 1"))
    return {"status": "ready"}


app.include_router(meta.router)
app.include_router(sessions.router)
app.include_router(imports.router)
app.include_router(analyses.router)
app.include_router(ingest.router)
app.include_router(crossmodal.router)
app.include_router(research.router)
