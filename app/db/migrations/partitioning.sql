-- Масштабирование на 1 млн пациентов.
--
-- Порядок величин: 1 млн пациентов × ~2 сессии в год × ~10 проб × ~20 параметров
-- ≈ 400 млн строк param_values в год. Это не «много» для Postgres при условии,
-- что запросы не читают всю таблицу — отсюда партиционирование по времени
-- и точечные индексы.

-- ── 1. Партиционирование по диапазону дат ──────────────────────────────────
-- Кандидаты: sessions, param_values, audit_log. Отсечение партиций делает
-- когортный запрос за квартал дешёвым независимо от общего объёма.

-- ALTER TABLE param_values RENAME TO param_values_old;
-- CREATE TABLE param_values (LIKE param_values_old INCLUDING ALL)
--   PARTITION BY RANGE (observed_at);
-- CREATE TABLE param_values_2026q1 PARTITION OF param_values
--   FOR VALUES FROM ('2026-01-01') TO ('2026-04-01');

-- ── 2. audit_log — только вставка (§4 инвариант 4, §15) ────────────────────
REVOKE UPDATE, DELETE ON audit_log FROM PUBLIC;
-- CREATE ROLE diers_app LOGIN;
-- GRANT SELECT, INSERT ON audit_log TO diers_app;
-- Отзыв прав на уровне БД, а не проверка в коде: приложение скомпрометировано —
-- журнал всё равно неизменяем.

-- ── 3. Индексы под фактические запросы ─────────────────────────────────────
CREATE INDEX IF NOT EXISTS ix_param_values_cohort
  ON param_values (param_code, probe_code, observed_at) INCLUDE (value);

CREATE INDEX IF NOT EXISTS ix_analyses_session_created
  ON analyses (session_id, created_at DESC);

-- Поиск «все пациенты со значением параметра выше X» — ради него и существует
-- витрина param_values: по JSONB это полный перебор.
CREATE INDEX IF NOT EXISTS ix_param_values_value
  ON param_values (param_code, value) WHERE value IS NOT NULL;

-- Частичный индекс: сессий с низкой достоверностью мало, а спрашивают о них часто.
CREATE INDEX IF NOT EXISTS ix_sessions_low_confidence
  ON sessions (started_at DESC) WHERE low_confidence;

-- ── 4. Хранение analyses (Р-34) ────────────────────────────────────────────
-- Вытеснению подлежат строки, НЕ подписанные и НЕ входящие ни в одну когорту.
-- Подписанные и когортные хранятся всегда: этого требуют §1 (проверяемость
-- заключения) и §7 исследовательского контура (воспроизводимость).
--
-- DELETE FROM analyses a
--  WHERE a.created_at < now() - interval '18 months'
--    AND NOT EXISTS (SELECT 1 FROM reports r WHERE r.analysis_id = a.id AND r.status='signed')
--    AND NOT EXISTS (SELECT 1 FROM cohorts c WHERE a.session_id::text = ANY(
--          SELECT jsonb_array_elements_text(c.session_ids)))
--    AND a.id <> (SELECT id FROM analyses x WHERE x.session_id = a.session_id
--                  ORDER BY created_at DESC LIMIT 1);
