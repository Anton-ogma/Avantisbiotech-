from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DIERS_", env_file=".env", extra="ignore")

    # ── Регуляторная граница (Р-25). Не флаг функциональности. ────────────────
    intended_use: Literal["research", "clinical"] = "research"
    registration_number: str | None = None

    # ── Хранилище ─────────────────────────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://diers:diers@localhost:5432/diers"
    redis_url: str = "redis://localhost:6379/0"
    s3_endpoint: str = "http://localhost:9000"
    s3_bucket: str = "diers-raw"

    #: Масштабирование: пул на процесс. При 1 млн пациентов узкое место —
    #: не число строк, а число соединений; поэтому pgbouncer в transaction-режиме
    #: перед этим пулом, а не вместо него.
    db_pool_size: int = 20
    db_max_overflow: int = 10
    db_pool_timeout: int = 10

    # ── Версии конфигурации (пять, входят в input_hash; Р-3) ──────────────────
    registry_version: str = "2026.6"
    profile_version: str = "2026.6"
    thresholds_version: str = "demo-2026.6"
    norms_version: str = "empty"
    protocol_version: str = "2026.1"
    rules_version: str = "none"

    # ── Замкнутость контура (Р-23) ────────────────────────────────────────────
    #: MUST: ФЗ-152 ст. 18 ч. 5 — локализация; ст. 12 — трансграничная передача.
    #: Ни один сценарий не обращается к внешним хостам. LLM — только в контуре.
    allow_external_calls: bool = False
    llm_endpoint: str | None = None

    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    audit_retention_days: int = 3650

    @model_validator(mode="after")
    def _guard(self) -> "Settings":
        if self.intended_use == "clinical" and not self.registration_number:
            # MUST (Р-25): ПО для диагностики и лечения — медизделие (ФЗ-323 ст. 38),
            # эксплуатация без РУ запрещена. Сборка не стартует.
            raise ValueError(
                "intended_use=clinical требует DIERS_REGISTRATION_NUMBER — "
                "регистрационного удостоверения медицинского изделия (ПП РФ № 1416; "
                "Решение Совета ЕЭК № 46). Для исследований используйте research."
            )
        if self.llm_endpoint and not self.allow_external_calls:
            host = self.llm_endpoint.split("//")[-1].split("/")[0].split(":")[0]
            if host not in ("localhost", "127.0.0.1") and not host.endswith(".local"):
                raise ValueError(
                    f"llm_endpoint={host} вне контура организации. Отправка фрагмента "
                    "заключения во внешний сервис — трансграничная передача специальной "
                    "категории ПДн (ФЗ-152, ст. 12). Разверните модель on-prem (Р-23)."
                )
        return self

    @property
    def banners(self) -> list[str]:
        out: list[str] = []
        if self.thresholds_version == "demo" or "demo" in self.thresholds_version:
            out.append(
                "Пороги некалиброваны (source=demo): суждения о значимости недействительны. "
                "Запустите режим повторяемости для выпуска собственного SDC."
            )
        if self.norms_version == "empty":
            out.append("Нормы не заданы — используется RI. PI не вычисляется (это штатно).")
        if self.intended_use == "research":
            out.append(
                "Режим research: платформа не является медицинским изделием, "
                "терапевтических назначений не выдаёт."
            )
        return out


@lru_cache
def get_settings() -> Settings:
    return Settings()
