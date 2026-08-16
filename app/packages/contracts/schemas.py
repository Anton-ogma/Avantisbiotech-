from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

SessionStatus = Literal[
    "prepared", "plan_approved", "baseline_recorded", "probes_running",
    "imported", "quality_reviewed", "shortlist_confirmed", "analyzed", "reported",
]
Role = Literal["operator", "clinician", "methodologist", "coach", "admin"]
ReportVariant = Literal["doctor", "patient", "dentist", "coach"]
IntendedUse = Literal["research", "clinical"]


class Base(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")


# ── Конфигурация и режим ─────────────────────────────────────────────────────

class ConfigVersions(Base):
    norms_version: str
    thresholds_version: str
    rules_version: str
    profile_version: str
    registry_version: str


class PlatformInfo(Base):
    intended_use: IntendedUse
    registration_number: str | None = None
    versions: ConfigVersions
    protocol_version: str
    thresholds_are_demo: bool
    norms_defined: bool
    #: MUST §10: показывается на экранах анализа, рекомендаций и в отчёте.
    banners: list[str] = Field(default_factory=list)


class ParamInfo(Base):
    code: str
    label_ru: str
    unit: str
    domain: str
    direction: Literal["two_sided", "higher_worse", "lower_worse", "unknown"]
    in_pi: bool
    sdc: float | None
    norm_defined: bool
    direction_evidence: str | None = None


class ProbeInfo(Base):
    code: str
    label_ru: str
    group: str
    role: str
    settle_sec: int
    carryover_min: int
    is_neutral: bool
    shams_group: str | None = None


# ── Сессия и план ────────────────────────────────────────────────────────────

class SessionCreate(Base):
    patient_ref: str = Field(min_length=8, description="Непроизводен от ПДн и неперечислим (Р-9)")
    neutral_definition: Literal["physiological_rest", "habitual_occlusion"]
    #: MUST (Р-24): без действующего ИДС сессия НЕ СОЗДАЁТСЯ. Согласие предшествует
    #: вмешательству, а не сопровождает его — проверка на неявном переходе бесполезна.
    informed_consent_ref: str = Field(min_length=1)
    operator_ref: str
    study_mode: bool = False
    research_consent_ref: str | None = None
    lld_mm: float | None = None
    platform_config_baseline: dict[str, Any] = Field(default_factory=dict)
    randomization_scheme: Literal["none", "random_within_group", "counterbalanced"] = "none"
    randomization_seed: int | None = None
    patient_blinded: bool | None = None
    operator_blinded: bool | None = None

    @field_validator("patient_ref")
    @classmethod
    def _not_enumerable(cls, v: str) -> str:
        if v.isdigit():
            raise ValueError(
                "patient_ref не может быть последовательным идентификатором хоста: "
                "он перечислим и тривиально сопоставим с профилем (Р-9)"
            )
        return v


class PlannedProbeIn(Base):
    probe_code: str
    position: int
    pass_no: int = 1


class PlanCreate(Base):
    probes: list[PlannedProbeIn]
    apply_randomization: bool = True


class ViolationOut(Base):
    code: str
    message: str
    blocking: bool


class PlanOut(Base):
    session_id: UUID
    probes: list[PlannedProbeIn]
    approved_by: str | None
    approved_at: datetime | None
    violations: list[ViolationOut] = Field(default_factory=list)
    deviations: list[dict[str, Any]] = Field(default_factory=list)


class TrialCreate(Base):
    probe_code: str
    role: str
    mode: Literal["static", "dynamic"] = "static"
    pass_no: int = 1
    position: int
    t_offset_sec: float = Field(ge=0, description="Секунды от начала сессии, не системные часы")
    settle_sec_actual: int = 0
    minutes_since_prev_group: float | None = None
    excursion_mm: float | None = None
    effort_achieved_pct: float | None = None
    platform_config: dict[str, Any] = Field(default_factory=dict)


class SessionOut(Base):
    id: UUID
    patient_ref: str
    status: SessionStatus
    study_mode: bool
    neutral_definition: str
    low_confidence: bool
    started_at: datetime
    operator_ref: str
    versions: ConfigVersions
    protocol_version: str
    trial_count: int = 0
    pass_count: int = 1


# ── Импорт ───────────────────────────────────────────────────────────────────

class ImportOut(Base):
    id: UUID
    file_hash: str
    modality: str | None
    format_id: str | None
    source: Literal["agent", "manual"]
    status: Literal["queued", "parsed", "unrecognized", "failed"]
    reason: str | None
    created_at: datetime
    measurements: int = 0


# ── Разбор качества и шорт-лист ──────────────────────────────────────────────

class QualityItem(Base):
    """MUST (Р-17): код пробы, роль, порядковый номер и результаты анализа
    на этом экране НЕ ОТДАЮТСЯ до фиксации всех решений."""

    measurement_id: UUID
    modality: str
    quality_flags: list[str]
    param_count: int


class QualityDecision(Base):
    measurement_id: UUID
    verdict: Literal["accept", "exclude"]
    reason_code: str
    reason_text: str | None = None


class QualityReviewIn(Base):
    decisions: list[QualityDecision]


class ShortlistIn(Base):
    confirmed_probe_codes: list[str]


class InterimOut(Base):
    """MUST (Р-28): ТОЛЬКО коды. Величины раскрываются после закрытия разбора."""

    probe_codes: list[str]
    note: str = "Величины скрыты до закрытия разбора качества (Р-17, Р-28)"


# ── Анализ и отчёт ───────────────────────────────────────────────────────────

class AnalyzeIn(Base):
    versions: ConfigVersions | None = None


class AnalysisOut(Base):
    id: UUID
    session_id: UUID
    input_hash: str
    versions: ConfigVersions
    index_kind: Literal["RI", "PI"]
    created_at: datetime
    result: dict[str, Any]


class ReportCreate(Base):
    variant: ReportVariant


class ReportOut(Base):
    id: UUID
    analysis_id: UUID
    variant: ReportVariant
    status: Literal["draft", "signed"]
    document_hash: str
    signed_by: str | None
    signed_at: datetime | None
    watermark: bool


class SignIn(Base):
    """MUST (Р-22): подписывается ХЭШ СФОРМИРОВАННОГО ДОКУМЕНТА, а не запись в БД.
    ФЗ-63; Приказ МЗ РФ № 947н. Нажатие кнопки медицинским документом отчёт не делает."""

    clinician_ref: str
    signature: str = Field(min_length=16, description="Отсоединённая УКЭП, base64")
    signed_document_hash: str
    timestamp_token: str | None = Field(
        default=None,
        description="Метка доверенного времени; без неё истечение сертификата "
                    "обесценивает подпись задним числом",
    )


# ── Метрология и исследование ────────────────────────────────────────────────

class PassportOut(Base):
    code: str
    label_ru: str
    n_subjects: int
    n_measurements: int
    icc: float | None
    icc_ci: list[float] | None
    sem: float | None
    sdc: float | None
    cv_pct: float | None
    reliability: str
    detectable_at_n30: float | None


class RepeatabilityOut(Base):
    passports: list[PassportOut]
    operator_variance_share: float | None
    warning: str | None


class CohortCreate(Base):
    name: str
    criteria: dict[str, Any] = Field(default_factory=dict)
    session_ids: list[UUID]
    lockbox_share: float = Field(default=0.3, ge=0.0, lt=1.0)


class CohortOut(Base):
    id: UUID
    name: str
    session_ids: list[UUID]
    lockbox_session_ids: list[UUID]
    frozen_at: datetime
    lockbox_opened_at: datetime | None


class HypothesisCreate(Base):
    statement: str = Field(min_length=10)
    params: list[str]
    probe_codes: list[str]
    expected_direction: Literal["improving", "worsening", "any", "unspecified"] = "unspecified"
    analysis_plan: dict[str, Any]
    cohort_criteria: dict[str, Any] = Field(default_factory=dict)
    target_n: int = Field(ge=1)
    mode: Literal["exploratory", "confirmatory"]


class HypothesisOut(Base):
    id: UUID
    statement: str
    mode: Literal["exploratory", "confirmatory"]
    status: str
    target_n: int
    plan_hash: str
    registered_at: datetime
    registered_by: str
    power_note: str | None = None


class CohortAnalysisOut(Base):
    id: UUID
    cohort_id: UUID
    hypothesis_id: UUID | None
    mode: Literal["exploratory", "confirmatory"]
    comparisons_tested: int
    input_hash: str
    created_at: datetime
    result: dict[str, Any]
    disclaimer: str


class ProtocolAnalyticsOut(Base):
    """Слой 2 аналитики (§9.8а): платформа изучает собственный протокол."""

    settle_calibration: list[dict[str, Any]]
    carryover_calibration: list[dict[str, Any]]
    yield_by_probe: list[dict[str, Any]]
    deviation_summary: list[dict[str, Any]]
    low_confidence_share: float | None
