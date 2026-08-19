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
    registry_version: str = "2026.7"
    profile_version: str = "2026.7"
    thresholds_version: str = "demo-2026.7"
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

    # ── Доверие к вызывающей стороне (§15) ────────────────────────────────────
    #: Аутентификация пользователя вынесена за модуль: заверенный контекст —
    #: актор и роль — приходит от хоста заголовками. Но ЧТО запрос пришёл именно
    #: от хоста, до сих пор не проверялось ничем: кто дотянулся до порта, тот и
    #: представлялся `X-Actor-Role: admin`. Общий секрет закрывает эту дыру, не
    #: втаскивая в модуль пользовательскую аутентификацию: хост подписывает свои
    #: вызовы, модуль их принимает, а всё остальное отвергает.
    #:
    #: Пустое значение допустимо только в research и только с баннером: без
    #: секрета контур открыт всем, кто видит порт.
    gateway_token: str | None = None
    #: Предел размера тела запроса. До этого его не было вовсе: выгрузка на
    #: гигабайт спокойно принималась в память процесса.
    max_upload_mb: int = 32

    @model_validator(mode="after")
    def _guard(self) -> Settings:
        if self.intended_use == "clinical" and not self.registration_number:
            # MUST (Р-25): ПО для диагностики и лечения — медизделие (ФЗ-323 ст. 38),
            # эксплуатация без РУ запрещена. Сборка не стартует.
            raise ValueError(
                "intended_use=clinical требует DIERS_REGISTRATION_NUMBER — "
                "регистрационного удостоверения медицинского изделия (ПП РФ № 1416; "
                "Решение Совета ЕЭК № 46). Для исследований используйте research."
            )
        if self.intended_use == "clinical" and not self.gateway_token:
            # Клинический контур без проверки вызывающей стороны — открытый
            # доступ к специальной категории ПДн (ФЗ-152 ст. 10). Роль и актор
            # приходят заголовками, и без общего секрета их назначает себе
            # любой, кто видит порт.
            raise ValueError(
                "intended_use=clinical требует DIERS_GATEWAY_TOKEN — общего секрета "
                "с хостом. Без него заголовки X-Actor-Role подделываются кем угодно."
            )
        if self.gateway_token is not None and len(self.gateway_token) < 32:
            raise ValueError(
                "DIERS_GATEWAY_TOKEN короче 32 символов: подбирается перебором. "
                "Сгенерируйте `openssl rand -hex 32`."
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
        if not self.gateway_token:
            out.append(
                "Контур не защищён: общий секрет с хостом (DIERS_GATEWAY_TOKEN) не задан, "
                "и роль вызывающей стороны ничем не подтверждается. Допустимо только "
                "на изолированном стенде."
            )
        return out


@lru_cache
def get_settings() -> Settings:
    return Settings()
