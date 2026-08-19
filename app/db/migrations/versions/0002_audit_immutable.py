"""Неизменяемость журнала аудита и индексы под фактические запросы.

§4 инвариант 4 и §15 требуют, чтобы audit_log был INSERT ONLY. В моделях это
записано словами, а в базе не обеспечивалось ничем: `partitioning.sql` лежал
рядом как справка и не применялся ничем, а `REVOKE ... FROM PUBLIC` в нём
владельца таблицы не ограничивает — приложение подключается своей ролью и
спокойно удалило бы строки.

Поэтому запрет ставится ТРИГГЕРОМ. Он действует на любую роль, включая
владельца и суперпользователя, и переживает компрометацию приложения: журнал
неизменяем свойством базы, а не дисциплиной кода. Именно этого требует
ФЗ-152 ст. 21 — без целостного журнала состав выгрузки не восстановить.

На sqlite (демо и тесты) миграция — осознанный no-op: журнал там живёт внутри
временного файла и регуляторной нагрузки не несёт.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = '0002_audit_immutable'
down_revision: str | None = '0001_initial'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TRIGGER_FN = """
CREATE OR REPLACE FUNCTION diers_audit_immutable() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'audit_log неизменяем: разрешена только вставка (§4 инвариант 4)';
END;
$$ LANGUAGE plpgsql;
"""


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    op.execute(TRIGGER_FN)
    op.execute("""
        CREATE TRIGGER diers_audit_no_update BEFORE UPDATE OR DELETE ON audit_log
        FOR EACH ROW EXECUTE FUNCTION diers_audit_immutable();
    """)
    op.execute("REVOKE UPDATE, DELETE, TRUNCATE ON audit_log FROM PUBLIC")

    # Индексы под запросы, которые в модуле действительно есть: когортная
    # выборка по параметру за период, история анализов сессии, поиск «значение
    # выше X» (ради него витрина param_values и существует — по JSONB это
    # полный перебор) и сессии с низкой достоверностью: их мало, а спрашивают
    # о них часто, поэтому индекс частичный.
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_param_values_cohort
          ON param_values (param_code, probe_code, observed_at) INCLUDE (value)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_analyses_session_created
          ON analyses (session_id, created_at DESC)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_param_values_value
          ON param_values (param_code, value) WHERE value IS NOT NULL
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_sessions_low_confidence
          ON sessions (started_at DESC) WHERE low_confidence
    """)


def downgrade() -> None:
    if not _is_postgres():
        return
    op.execute("DROP INDEX IF EXISTS ix_sessions_low_confidence")
    op.execute("DROP INDEX IF EXISTS ix_param_values_value")
    op.execute("DROP INDEX IF EXISTS ix_analyses_session_created")
    op.execute("DROP INDEX IF EXISTS ix_param_values_cohort")
    op.execute("DROP TRIGGER IF EXISTS diers_audit_no_update ON audit_log")
    op.execute("DROP FUNCTION IF EXISTS diers_audit_immutable()")
