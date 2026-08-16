"""Схема БД (§4 ТЗ + Р-29, Р-34 + исследовательский контур §11).

Замечания по масштабированию на 1 млн пациентов:
  • sessions, measurements, audit_log, param_values — кандидаты на декларативное
    партиционирование по диапазону дат (см. db/migrations/partitioning.sql).
  • analyses имеет UNIQUE (session_id, input_hash): автопереанализ при неизменной
    конфигурации не создаёт строк вовсе, а не плодит дубликаты (Р-34).
  • param_values — денормализованная витрина для когортных запросов: JSONB хорош
    для хранения, но «все пациенты со Scoliosis > 10°» по нему читается плохо.
  • audit_log — INSERT ONLY, права на UPDATE/DELETE отзываются миграцией
    (§4 инвариант 4).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer,
    LargeBinary, String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON, TypeDecorator


class JSONB_(TypeDecorator):
    """JSONB на Postgres, JSON на SQLite — тесты не требуют поднятого кластера."""

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        return dialect.type_descriptor(JSONB() if dialect.name == "postgresql" else JSON())


class GUID(TypeDecorator):
    impl = String(36)
    cache_ok = True

    def load_dialect_impl(self, dialect):
        return dialect.type_descriptor(PGUUID(as_uuid=True) if dialect.name == "postgresql" else String(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return value if dialect.name == "postgresql" else str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


class Base(DeclarativeBase):
    pass


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


def _now() -> datetime:
    return datetime.now(timezone.utc)


class PatientRef(Base):
    __tablename__ = "patients_ref"
    #: ПДн внутрь модуля не попадают (§13, Р-9). Таблица соответствия — у хоста.
    patient_ref: Mapped[str] = mapped_column(String(128), primary_key=True)
    neutral_definition: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    #: Отзыв согласия (ФЗ-152 ст. 9 ч. 2, Р-24): хост уничтожает соответствие,
    #: модуль помечает ref несопоставимым. Данные остаются обезличенными.
    unlinked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Session(Base):
    __tablename__ = "sessions"
    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=_uuid)
    patient_ref: Mapped[str] = mapped_column(ForeignKey("patients_ref.patient_ref"), index=True)
    protocol_version: Mapped[str] = mapped_column(String(32))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    operator_ref: Mapped[str] = mapped_column(String(128))
    study_mode: Mapped[bool] = mapped_column(Boolean, default=False)
    randomization_scheme: Mapped[str] = mapped_column(String(32), default="none")
    randomization_seed: Mapped[int | None] = mapped_column(Integer)
    patient_blinded: Mapped[bool | None] = mapped_column(Boolean)
    operator_blinded: Mapped[bool | None] = mapped_column(Boolean)
    #: Копия значения на момент сессии (Р-8): смена у пациента прошлые сессии
    #: не переписывает.
    neutral_definition: Mapped[str] = mapped_column(String(32), nullable=False)
    lld_mm: Mapped[float | None] = mapped_column(Float)
    platform_config_baseline: Mapped[dict] = mapped_column(JSONB_, default=dict)
    #: Согласия (Р-24). Документы — у хоста, здесь признаки и реквизиты.
    informed_consent_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    research_consent_ref: Mapped[str | None] = mapped_column(String(128))
    #: Пять версий — копии значений, действовавших при обследовании (§4 инв. 3).
    norms_version: Mapped[str] = mapped_column(String(32))
    thresholds_version: Mapped[str] = mapped_column(String(32))
    rules_version: Mapped[str] = mapped_column(String(32))
    profile_version: Mapped[str] = mapped_column(String(32))
    registry_version: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="prepared", index=True)
    low_confidence: Mapped[bool] = mapped_column(Boolean, default=False)
    pass_count: Mapped[int] = mapped_column(Integer, default=1)

    trials: Mapped[list["Trial"]] = relationship(back_populates="session", cascade="all, delete-orphan")
    plan: Mapped["SessionPlan | None"] = relationship(back_populates="session", uselist=False,
                                                      cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint(
            "status IN ('prepared','plan_approved','baseline_recorded','probes_running',"
            "'imported','quality_reviewed','shortlist_confirmed','analyzed','reported')",
            name="ck_sessions_status",
        ),
        Index("ix_sessions_patient_started", "patient_ref", "started_at"),
    )


class SessionMontageRow(Base):
    """Монтаж ЭМГ сессии: какие каналы записаны (Р-42).

    Отдельная таблица, а не поле сессии: у монтажа своя история правок, и
    «кто и когда переназначил канал» — вопрос, который задают при разборе
    расхождений. Действующим считается последняя строка.
    """
    __tablename__ = "session_montages"
    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=_uuid)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    template: Mapped[str | None] = mapped_column(String(32))
    note: Mapped[str] = mapped_column(Text, default="")
    #: [{"label": "CH1", "muscle": "MASSETER", "side": "L"}, …]
    channels: Mapped[list] = mapped_column(JSONB_, default=list)
    set_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class SessionPlan(Base):
    """Р-29: план утверждается ДО первой пробы. Валидатор, срабатывающий после
    ухода пациента, ничего не предотвращает."""

    __tablename__ = "session_plans"
    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=_uuid)
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"),
                                                  unique=True, index=True)
    probes: Mapped[list] = mapped_column(JSONB_, default=list)
    randomization: Mapped[dict] = mapped_column(JSONB_, default=dict)
    approved_by: Mapped[str | None] = mapped_column(String(128))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    session: Mapped[Session] = relationship(back_populates="plan")


class ProtocolDeviation(Base):
    """Р-29 + ГОСТ Р ИСО 14155: отклонения — данные, а не ошибка."""

    __tablename__ = "protocol_deviations"
    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=_uuid)
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    trial_id: Mapped[uuid.UUID | None] = mapped_column(GUID)
    kind: Mapped[str] = mapped_column(String(32))
    probe_code: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(Text)
    recorded_by: Mapped[str] = mapped_column(String(128))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Trial(Base):
    __tablename__ = "trials"
    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=_uuid)
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    probe_code: Mapped[str] = mapped_column(String(64), index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    #: Проход; подтверждающий повтор — второй проход (Р-28).
    pass_no: Mapped[int] = mapped_column(Integer, default=1)
    role: Mapped[str] = mapped_column(String(32))
    mode: Mapped[str] = mapped_column(String(16), default="static")
    is_baseline: Mapped[bool] = mapped_column(Boolean, default=False)
    t_offset_sec: Mapped[float] = mapped_column(Float, default=0.0)
    settle_sec_actual: Mapped[int] = mapped_column(Integer, default=0)
    washout_sec_actual: Mapped[int] = mapped_column(Integer, default=0)
    minutes_since_prev_group: Mapped[float | None] = mapped_column(Float)
    excursion_mm: Mapped[float | None] = mapped_column(Float)
    effort: Mapped[dict] = mapped_column(JSONB_, default=dict)
    platform_config: Mapped[dict] = mapped_column(JSONB_, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    session: Mapped[Session] = relationship(back_populates="trials")
    measurements: Mapped[list["Measurement"]] = relationship(back_populates="trial",
                                                             cascade="all, delete-orphan")
    __table_args__ = (Index("ix_trials_session_pass", "session_id", "pass_no", "ordinal"),)


class RawImport(Base):
    __tablename__ = "raw_imports"
    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=_uuid)
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    #: §4 инвариант 1: идемпотентность. Повторная загрузка не создаёт второе обследование.
    file_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    modality: Mapped[str | None] = mapped_column(String(32))
    format_id: Mapped[str | None] = mapped_column(String(64))
    device_sw_version: Mapped[str | None] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(16), default="manual")
    status: Mapped[str] = mapped_column(String(16), default="queued")
    reason: Mapped[str | None] = mapped_column(Text)
    blob_ref: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ImportFigure(Base):
    """Иллюстрация приборного протокола (§5.1, Р-40).

    Хранится байтами рядом с импортом, а не в объектном хранилище: картинки
    протокола — десятки килобайт, их читают вместе с анализом, и отдельный
    round-trip в S3 на каждую был бы дороже самой картинки. Сырой файл целиком
    по-прежнему уходит в объектное хранилище (`RawImport.blob_ref`).

    ПДн здесь не появляются: реконструкция поверхности спины обезличена так же,
    как числа, — соответствие с человеком ведёт хост через `patient_ref` (Р-9).
    """
    __tablename__ = "import_figures"
    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=_uuid)
    raw_import_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("raw_imports.id", ondelete="CASCADE"), index=True)
    trial_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("trials.id", ondelete="CASCADE"), index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(16))       # render | caption
    mime: Mapped[str] = mapped_column(String(32))
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    data: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Measurement(Base):
    __tablename__ = "measurements"
    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=_uuid)
    trial_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("trials.id", ondelete="CASCADE"), index=True)
    raw_import_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("raw_imports.id"))
    modality: Mapped[str] = mapped_column(String(32))
    params: Mapped[dict] = mapped_column(JSONB_, default=dict)
    frames: Mapped[dict | None] = mapped_column(JSONB_)
    unmapped: Mapped[dict] = mapped_column(JSONB_, default=dict)
    quality_flags: Mapped[list] = mapped_column(JSONB_, default=list)
    excluded: Mapped[bool] = mapped_column(Boolean, default=False)
    trial: Mapped[Trial] = relationship(back_populates="measurements")


class ParamValue(Base):
    """Витрина для когортных запросов. JSONB хорош для хранения, но плох для
    «все пациенты со значением параметра выше X» — здесь плоско и индексируемо."""

    __tablename__ = "param_values"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[uuid.UUID] = mapped_column(GUID, index=True)
    trial_id: Mapped[uuid.UUID] = mapped_column(GUID, index=True)
    probe_code: Mapped[str] = mapped_column(String(64))
    pass_no: Mapped[int] = mapped_column(Integer, default=1)
    param_code: Mapped[str] = mapped_column(String(64))
    value: Mapped[float] = mapped_column(Float)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    __table_args__ = (
        Index("ix_param_values_code_value", "param_code", "value"),
        Index("ix_param_values_probe_code", "probe_code", "param_code"),
    )


class Exclusion(Base):
    """Р-17: исключения ОБРАТИМЫ. Необратимое равносильно потере данных."""

    __tablename__ = "exclusions"
    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=_uuid)
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    entity: Mapped[str] = mapped_column(String(32))
    entity_id: Mapped[uuid.UUID] = mapped_column(GUID)
    reason_code: Mapped[str] = mapped_column(String(64))
    reason_text: Mapped[str | None] = mapped_column(Text)
    decided_by: Mapped[str] = mapped_column(String(128))
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    blinded: Mapped[bool] = mapped_column(Boolean, default=True)
    reverted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Analysis(Base):
    __tablename__ = "analyses"
    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=_uuid)
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    norms_version: Mapped[str] = mapped_column(String(32))
    thresholds_version: Mapped[str] = mapped_column(String(32))
    rules_version: Mapped[str] = mapped_column(String(32))
    profile_version: Mapped[str] = mapped_column(String(32))
    registry_version: Mapped[str] = mapped_column(String(32))
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    index_kind: Mapped[str] = mapped_column(String(4), default="RI")
    result: Mapped[dict] = mapped_column(JSONB_, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    #: Ключ дешёвого автопереанализа (Р-34): тот же вход и те же версии дают тот же
    #: хэш, вставка отбрасывается — рост «сессии × версии» не наступает.
    __table_args__ = (UniqueConstraint("session_id", "input_hash", name="uq_analysis_input"),)


class Report(Base):
    __tablename__ = "reports"
    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=_uuid)
    analysis_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("analyses.id", ondelete="CASCADE"), index=True)
    variant: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="draft")
    #: Р-22: подписывается ХЭШ ДОКУМЕНТА, а не запись в БД.
    document_hash: Mapped[str] = mapped_column(String(64))
    pdf_ref: Mapped[str | None] = mapped_column(String(512))
    signature: Mapped[str | None] = mapped_column(Text)
    timestamp_token: Mapped[str | None] = mapped_column(Text)
    signed_by: Mapped[str | None] = mapped_column(String(128))
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    superseded_by: Mapped[uuid.UUID | None] = mapped_column(GUID)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Cohort(Base):
    __tablename__ = "cohorts"
    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(256))
    criteria: Mapped[dict] = mapped_column(JSONB_, default=dict)
    session_ids: Mapped[list] = mapped_column(JSONB_, default=list)
    lockbox_session_ids: Mapped[list] = mapped_column(JSONB_, default=list)
    frozen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    #: Однократно и необратимо (§7 исследовательского контура).
    lockbox_opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    hypothesis_id: Mapped[uuid.UUID | None] = mapped_column(GUID)


class Hypothesis(Base):
    __tablename__ = "hypotheses"
    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=_uuid)
    statement: Mapped[str] = mapped_column(Text)
    params: Mapped[list] = mapped_column(JSONB_, default=list)
    probe_codes: Mapped[list] = mapped_column(JSONB_, default=list)
    expected_direction: Mapped[str] = mapped_column(String(16), default="unspecified")
    analysis_plan: Mapped[dict] = mapped_column(JSONB_, default=dict)
    cohort_criteria: Mapped[dict] = mapped_column(JSONB_, default=dict)
    target_n: Mapped[int] = mapped_column(Integer, default=1)
    mode: Mapped[str] = mapped_column(String(16), default="exploratory")
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    registered_by: Mapped[str] = mapped_column(String(128))
    #: Неизменяемость регистрации: любое изменение плана меняет хэш и видно.
    plan_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="registered")


class CohortAnalysis(Base):
    __tablename__ = "cohort_analyses"
    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=_uuid)
    cohort_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cohorts.id", ondelete="CASCADE"), index=True)
    hypothesis_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("hypotheses.id"))
    mode: Mapped[str] = mapped_column(String(16))
    norms_version: Mapped[str] = mapped_column(String(32))
    thresholds_version: Mapped[str] = mapped_column(String(32))
    rules_version: Mapped[str] = mapped_column(String(32))
    profile_version: Mapped[str] = mapped_column(String(32))
    registry_version: Mapped[str] = mapped_column(String(32))
    #: Размер семейства для FDR — по фактически проверенным сочетаниям,
    #: а не по отобранным после просмотра.
    comparisons_tested: Mapped[int] = mapped_column(Integer, default=0)
    fdr_method: Mapped[str] = mapped_column(String(32), default="benjamini_hochberg")
    fdr_q: Mapped[float] = mapped_column(Float, default=0.05)
    exclusion_set_hash: Mapped[str] = mapped_column(String(64))
    deviations: Mapped[dict] = mapped_column(JSONB_, default=dict)
    input_hash: Mapped[str] = mapped_column(String(64))
    result: Mapped[dict] = mapped_column(JSONB_, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AuditLog(Base):
    """§4 инвариант 4 и §15: только вставка; UPDATE/DELETE отзываются миграцией.

    MUST (Р-21): фиксируется СОСТАВ выгрузки, а не только факт. ФЗ-152 ст. 21 даёт
    24 часа на уведомление об инциденте — без состава круг затронутых субъектов
    за сутки не определить.
    """

    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor: Mapped[str] = mapped_column(String(128), index=True)
    role: Mapped[str] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(64), index=True)
    entity: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    before_hash: Mapped[str | None] = mapped_column(String(64))
    after_hash: Mapped[str | None] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSONB_, default=dict)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
