"""Начальная схема: 17 таблиц модуля (§4 ТЗ).

До появления этого файла схема на Postgres не создавалась ВООБЩЕ: автосоздание
из моделей в `main.py` включено только для sqlite, а `make migrate` звал alembic,
которого в репозитории не было. Прод в таком виде не поднимался.

Сгенерировано автоматически из моделей и проверено вручную: собственные типы
`GUID` и `JSONB_` оставлены своими — подмена их на `sa.JSON()` записала бы в
схему не тот тип, который приложение ожидает на Postgres.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from apps.api import models

revision: str = '0001_initial'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('audit_log',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('actor', sa.String(length=128), nullable=False),
    sa.Column('role', sa.String(length=32), nullable=False),
    sa.Column('action', sa.String(length=64), nullable=False),
    sa.Column('entity', sa.String(length=64), nullable=False),
    sa.Column('entity_id', sa.String(length=64), nullable=True),
    sa.Column('before_hash', sa.String(length=64), nullable=True),
    sa.Column('after_hash', sa.String(length=64), nullable=True),
    sa.Column('payload', models.JSONB_(), nullable=False),
    sa.Column('ts', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_audit_log_action'), 'audit_log', ['action'], unique=False)
    op.create_index(op.f('ix_audit_log_actor'), 'audit_log', ['actor'], unique=False)
    op.create_index(op.f('ix_audit_log_ts'), 'audit_log', ['ts'], unique=False)
    op.create_table('cohorts',
    sa.Column('id', models.GUID(), nullable=False),
    sa.Column('name', sa.String(length=256), nullable=False),
    sa.Column('criteria', models.JSONB_(), nullable=False),
    sa.Column('session_ids', models.JSONB_(), nullable=False),
    sa.Column('lockbox_session_ids', models.JSONB_(), nullable=False),
    sa.Column('frozen_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('lockbox_opened_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('hypothesis_id', models.GUID(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('hypotheses',
    sa.Column('id', models.GUID(), nullable=False),
    sa.Column('statement', sa.Text(), nullable=False),
    sa.Column('params', models.JSONB_(), nullable=False),
    sa.Column('probe_codes', models.JSONB_(), nullable=False),
    sa.Column('expected_direction', sa.String(length=16), nullable=False),
    sa.Column('analysis_plan', models.JSONB_(), nullable=False),
    sa.Column('cohort_criteria', models.JSONB_(), nullable=False),
    sa.Column('target_n', sa.Integer(), nullable=False),
    sa.Column('mode', sa.String(length=16), nullable=False),
    sa.Column('registered_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('registered_by', sa.String(length=128), nullable=False),
    sa.Column('plan_hash', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('montage_templates',
    sa.Column('id', models.GUID(), nullable=False),
    sa.Column('code', sa.String(length=64), nullable=False),
    sa.Column('label_ru', sa.String(length=128), nullable=False),
    sa.Column('purpose', sa.Text(), nullable=False),
    sa.Column('channels', models.JSONB_(), nullable=False),
    sa.Column('created_by', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('archived', sa.Boolean(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_montage_templates_code'), 'montage_templates', ['code'], unique=True)
    op.create_table('param_values',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('session_id', models.GUID(), nullable=False),
    sa.Column('trial_id', models.GUID(), nullable=False),
    sa.Column('probe_code', sa.String(length=64), nullable=False),
    sa.Column('pass_no', sa.Integer(), nullable=False),
    sa.Column('param_code', sa.String(length=64), nullable=False),
    sa.Column('value', sa.Float(), nullable=False),
    sa.Column('observed_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_param_values_code_value', 'param_values', ['param_code', 'value'], unique=False)
    op.create_index('ix_param_values_probe_code', 'param_values', ['probe_code', 'param_code'], unique=False)
    op.create_index(op.f('ix_param_values_session_id'), 'param_values', ['session_id'], unique=False)
    op.create_index(op.f('ix_param_values_trial_id'), 'param_values', ['trial_id'], unique=False)
    op.create_table('patients_ref',
    sa.Column('patient_ref', sa.String(length=128), nullable=False),
    sa.Column('neutral_definition', sa.String(length=32), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('unlinked_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('patient_ref')
    )
    op.create_table('cohort_analyses',
    sa.Column('id', models.GUID(), nullable=False),
    sa.Column('cohort_id', models.GUID(), nullable=False),
    sa.Column('hypothesis_id', models.GUID(), nullable=True),
    sa.Column('mode', sa.String(length=16), nullable=False),
    sa.Column('norms_version', sa.String(length=32), nullable=False),
    sa.Column('thresholds_version', sa.String(length=32), nullable=False),
    sa.Column('rules_version', sa.String(length=32), nullable=False),
    sa.Column('profile_version', sa.String(length=32), nullable=False),
    sa.Column('registry_version', sa.String(length=32), nullable=False),
    sa.Column('comparisons_tested', sa.Integer(), nullable=False),
    sa.Column('fdr_method', sa.String(length=32), nullable=False),
    sa.Column('fdr_q', sa.Float(), nullable=False),
    sa.Column('exclusion_set_hash', sa.String(length=64), nullable=False),
    sa.Column('deviations', models.JSONB_(), nullable=False),
    sa.Column('input_hash', sa.String(length=64), nullable=False),
    sa.Column('result', models.JSONB_(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['cohort_id'], ['cohorts.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['hypothesis_id'], ['hypotheses.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_cohort_analyses_cohort_id'), 'cohort_analyses', ['cohort_id'], unique=False)
    op.create_table('sessions',
    sa.Column('id', models.GUID(), nullable=False),
    sa.Column('patient_ref', sa.String(length=128), nullable=False),
    sa.Column('protocol_version', sa.String(length=32), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('operator_ref', sa.String(length=128), nullable=False),
    sa.Column('study_mode', sa.Boolean(), nullable=False),
    sa.Column('randomization_scheme', sa.String(length=32), nullable=False),
    sa.Column('randomization_seed', sa.Integer(), nullable=True),
    sa.Column('patient_blinded', sa.Boolean(), nullable=True),
    sa.Column('operator_blinded', sa.Boolean(), nullable=True),
    sa.Column('neutral_definition', sa.String(length=32), nullable=False),
    sa.Column('lld_mm', sa.Float(), nullable=True),
    sa.Column('platform_config_baseline', models.JSONB_(), nullable=False),
    sa.Column('informed_consent_ref', sa.String(length=128), nullable=False),
    sa.Column('research_consent_ref', sa.String(length=128), nullable=True),
    sa.Column('norms_version', sa.String(length=32), nullable=False),
    sa.Column('thresholds_version', sa.String(length=32), nullable=False),
    sa.Column('rules_version', sa.String(length=32), nullable=False),
    sa.Column('profile_version', sa.String(length=32), nullable=False),
    sa.Column('registry_version', sa.String(length=32), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('low_confidence', sa.Boolean(), nullable=False),
    sa.Column('pass_count', sa.Integer(), nullable=False),
    sa.CheckConstraint("status IN ('prepared','plan_approved','baseline_recorded','probes_running','imported','quality_reviewed','shortlist_confirmed','analyzed','reported')", name='ck_sessions_status'),
    sa.ForeignKeyConstraint(['patient_ref'], ['patients_ref.patient_ref'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_sessions_patient_ref'), 'sessions', ['patient_ref'], unique=False)
    op.create_index('ix_sessions_patient_started', 'sessions', ['patient_ref', 'started_at'], unique=False)
    op.create_index(op.f('ix_sessions_started_at'), 'sessions', ['started_at'], unique=False)
    op.create_index(op.f('ix_sessions_status'), 'sessions', ['status'], unique=False)
    op.create_table('analyses',
    sa.Column('id', models.GUID(), nullable=False),
    sa.Column('session_id', models.GUID(), nullable=False),
    sa.Column('norms_version', sa.String(length=32), nullable=False),
    sa.Column('thresholds_version', sa.String(length=32), nullable=False),
    sa.Column('rules_version', sa.String(length=32), nullable=False),
    sa.Column('profile_version', sa.String(length=32), nullable=False),
    sa.Column('registry_version', sa.String(length=32), nullable=False),
    sa.Column('input_hash', sa.String(length=64), nullable=False),
    sa.Column('index_kind', sa.String(length=4), nullable=False),
    sa.Column('result', models.JSONB_(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('session_id', 'input_hash', name='uq_analysis_input')
    )
    op.create_index(op.f('ix_analyses_session_id'), 'analyses', ['session_id'], unique=False)
    op.create_table('exclusions',
    sa.Column('id', models.GUID(), nullable=False),
    sa.Column('session_id', models.GUID(), nullable=False),
    sa.Column('entity', sa.String(length=32), nullable=False),
    sa.Column('entity_id', models.GUID(), nullable=False),
    sa.Column('reason_code', sa.String(length=64), nullable=False),
    sa.Column('reason_text', sa.Text(), nullable=True),
    sa.Column('decided_by', sa.String(length=128), nullable=False),
    sa.Column('decided_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('blinded', sa.Boolean(), nullable=False),
    sa.Column('reverted_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_exclusions_session_id'), 'exclusions', ['session_id'], unique=False)
    op.create_table('protocol_deviations',
    sa.Column('id', models.GUID(), nullable=False),
    sa.Column('session_id', models.GUID(), nullable=False),
    sa.Column('trial_id', models.GUID(), nullable=True),
    sa.Column('kind', sa.String(length=32), nullable=False),
    sa.Column('probe_code', sa.String(length=64), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('recorded_by', sa.String(length=128), nullable=False),
    sa.Column('recorded_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_protocol_deviations_session_id'), 'protocol_deviations', ['session_id'], unique=False)
    op.create_table('raw_imports',
    sa.Column('id', models.GUID(), nullable=False),
    sa.Column('session_id', models.GUID(), nullable=False),
    sa.Column('file_hash', sa.String(length=64), nullable=False),
    sa.Column('modality', sa.String(length=32), nullable=True),
    sa.Column('format_id', sa.String(length=64), nullable=True),
    sa.Column('device_sw_version', sa.String(length=64), nullable=True),
    sa.Column('source', sa.String(length=16), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('blob_ref', sa.String(length=512), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('file_hash')
    )
    op.create_index(op.f('ix_raw_imports_session_id'), 'raw_imports', ['session_id'], unique=False)
    op.create_table('session_montages',
    sa.Column('id', models.GUID(), nullable=False),
    sa.Column('session_id', models.GUID(), nullable=False),
    sa.Column('template', sa.String(length=32), nullable=True),
    sa.Column('note', sa.Text(), nullable=False),
    sa.Column('channels', models.JSONB_(), nullable=False),
    sa.Column('set_by', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_session_montages_session_id'), 'session_montages', ['session_id'], unique=False)
    op.create_table('session_plans',
    sa.Column('id', models.GUID(), nullable=False),
    sa.Column('session_id', models.GUID(), nullable=False),
    sa.Column('probes', models.JSONB_(), nullable=False),
    sa.Column('randomization', models.JSONB_(), nullable=False),
    sa.Column('approved_by', sa.String(length=128), nullable=True),
    sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_session_plans_session_id'), 'session_plans', ['session_id'], unique=True)
    op.create_table('trials',
    sa.Column('id', models.GUID(), nullable=False),
    sa.Column('session_id', models.GUID(), nullable=False),
    sa.Column('probe_code', sa.String(length=64), nullable=False),
    sa.Column('ordinal', sa.Integer(), nullable=False),
    sa.Column('pass_no', sa.Integer(), nullable=False),
    sa.Column('role', sa.String(length=32), nullable=False),
    sa.Column('mode', sa.String(length=16), nullable=False),
    sa.Column('is_baseline', sa.Boolean(), nullable=False),
    sa.Column('t_offset_sec', sa.Float(), nullable=False),
    sa.Column('settle_sec_actual', sa.Integer(), nullable=False),
    sa.Column('washout_sec_actual', sa.Integer(), nullable=False),
    sa.Column('minutes_since_prev_group', sa.Float(), nullable=True),
    sa.Column('excursion_mm', sa.Float(), nullable=True),
    sa.Column('effort', models.JSONB_(), nullable=False),
    sa.Column('platform_config', models.JSONB_(), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_trials_probe_code'), 'trials', ['probe_code'], unique=False)
    op.create_index(op.f('ix_trials_session_id'), 'trials', ['session_id'], unique=False)
    op.create_index('ix_trials_session_pass', 'trials', ['session_id', 'pass_no', 'ordinal'], unique=False)
    op.create_table('import_figures',
    sa.Column('id', models.GUID(), nullable=False),
    sa.Column('raw_import_id', models.GUID(), nullable=False),
    sa.Column('trial_id', models.GUID(), nullable=True),
    sa.Column('ordinal', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('mime', sa.String(length=32), nullable=False),
    sa.Column('width', sa.Integer(), nullable=False),
    sa.Column('height', sa.Integer(), nullable=False),
    sa.Column('structures', models.JSONB_(), nullable=False),
    sa.Column('page', sa.Integer(), nullable=False),
    sa.Column('data', sa.LargeBinary(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['raw_import_id'], ['raw_imports.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['trial_id'], ['trials.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_import_figures_raw_import_id'), 'import_figures', ['raw_import_id'], unique=False)
    op.create_index(op.f('ix_import_figures_trial_id'), 'import_figures', ['trial_id'], unique=False)
    op.create_table('measurements',
    sa.Column('id', models.GUID(), nullable=False),
    sa.Column('trial_id', models.GUID(), nullable=False),
    sa.Column('raw_import_id', models.GUID(), nullable=True),
    sa.Column('modality', sa.String(length=32), nullable=False),
    sa.Column('params', models.JSONB_(), nullable=False),
    sa.Column('frames', models.JSONB_(), nullable=True),
    sa.Column('unmapped', models.JSONB_(), nullable=False),
    sa.Column('quality_flags', models.JSONB_(), nullable=False),
    sa.Column('excluded', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['raw_import_id'], ['raw_imports.id'], ),
    sa.ForeignKeyConstraint(['trial_id'], ['trials.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_measurements_trial_id'), 'measurements', ['trial_id'], unique=False)
    op.create_table('reports',
    sa.Column('id', models.GUID(), nullable=False),
    sa.Column('analysis_id', models.GUID(), nullable=False),
    sa.Column('variant', sa.String(length=16), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('document_hash', sa.String(length=64), nullable=False),
    sa.Column('pdf_ref', sa.String(length=512), nullable=True),
    sa.Column('signature', sa.Text(), nullable=True),
    sa.Column('timestamp_token', sa.Text(), nullable=True),
    sa.Column('signed_by', sa.String(length=128), nullable=True),
    sa.Column('signed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('superseded_by', models.GUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['analysis_id'], ['analyses.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_reports_analysis_id'), 'reports', ['analysis_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_reports_analysis_id'), table_name='reports')
    op.drop_table('reports')
    op.drop_index(op.f('ix_measurements_trial_id'), table_name='measurements')
    op.drop_table('measurements')
    op.drop_index(op.f('ix_import_figures_trial_id'), table_name='import_figures')
    op.drop_index(op.f('ix_import_figures_raw_import_id'), table_name='import_figures')
    op.drop_table('import_figures')
    op.drop_index('ix_trials_session_pass', table_name='trials')
    op.drop_index(op.f('ix_trials_session_id'), table_name='trials')
    op.drop_index(op.f('ix_trials_probe_code'), table_name='trials')
    op.drop_table('trials')
    op.drop_index(op.f('ix_session_plans_session_id'), table_name='session_plans')
    op.drop_table('session_plans')
    op.drop_index(op.f('ix_session_montages_session_id'), table_name='session_montages')
    op.drop_table('session_montages')
    op.drop_index(op.f('ix_raw_imports_session_id'), table_name='raw_imports')
    op.drop_table('raw_imports')
    op.drop_index(op.f('ix_protocol_deviations_session_id'), table_name='protocol_deviations')
    op.drop_table('protocol_deviations')
    op.drop_index(op.f('ix_exclusions_session_id'), table_name='exclusions')
    op.drop_table('exclusions')
    op.drop_index(op.f('ix_analyses_session_id'), table_name='analyses')
    op.drop_table('analyses')
    op.drop_index(op.f('ix_sessions_status'), table_name='sessions')
    op.drop_index(op.f('ix_sessions_started_at'), table_name='sessions')
    op.drop_index('ix_sessions_patient_started', table_name='sessions')
    op.drop_index(op.f('ix_sessions_patient_ref'), table_name='sessions')
    op.drop_table('sessions')
    op.drop_index(op.f('ix_cohort_analyses_cohort_id'), table_name='cohort_analyses')
    op.drop_table('cohort_analyses')
    op.drop_table('patients_ref')
    op.drop_index(op.f('ix_param_values_trial_id'), table_name='param_values')
    op.drop_index(op.f('ix_param_values_session_id'), table_name='param_values')
    op.drop_index('ix_param_values_probe_code', table_name='param_values')
    op.drop_index('ix_param_values_code_value', table_name='param_values')
    op.drop_table('param_values')
    op.drop_index(op.f('ix_montage_templates_code'), table_name='montage_templates')
    op.drop_table('montage_templates')
    op.drop_table('hypotheses')
    op.drop_table('cohorts')
    op.drop_index(op.f('ix_audit_log_ts'), table_name='audit_log')
    op.drop_index(op.f('ix_audit_log_actor'), table_name='audit_log')
    op.drop_index(op.f('ix_audit_log_action'), table_name='audit_log')
    op.drop_table('audit_log')
