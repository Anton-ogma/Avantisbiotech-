.PHONY: help install dev seed test lint types up down migrate

help:
	@echo "install  — зависимости backend + frontend"
	@echo "dev      — API на 8000 и веб на 5173 (демо-БД sqlite)"
	@echo "seed     — демо-данные: 6 пациентов с полным протоколом"
	@echo "test     — pytest, вся таблица приёмки §16"
	@echo "lint     — ruff по всему коду"
	@echo "types    — mypy по домену и контрактам"
	@echo "check    — то же, что проверяет CI: линт, типы, тесты, миграции"
	@echo "migrate  — alembic upgrade head (нужен DIERS_DATABASE_URL)"
	@echo "up/down  — docker compose, on-prem развёртывание"

DEMO_DB := sqlite+aiosqlite:///$(PWD)/demo.db
PY := PYTHONPATH=$(PWD)/packages:$(PWD) DIERS_DATABASE_URL=$(DEMO_DB)

install:
	pip install -e ".[dev]"
	cd apps/web && npm install

seed:
	$(PY) python -m apps.api.seed

dev: seed
	$(PY) uvicorn apps.api.main:app --reload --port 8000 & \
	cd apps/web && npm run dev

test:
	PYTHONPATH=$(PWD)/packages:$(PWD) python -m pytest tests -q

lint:
	ruff check packages apps tools tests

types:
	mypy

# Ровно то, что гоняет CI: расхождение между «у меня всё зелено» и проверкой
# на сервере — источник самых дорогих сюрпризов.
check: lint types test
	DIERS_DATABASE_URL=$(DEMO_DB) $(PY) alembic upgrade head

up:
	@test -f .env || { echo "нет .env — скопируйте .env.example и заполните секреты"; exit 1; }
	docker compose up --build -d
	@echo "веб http://localhost:8080 (API наружу не публикуется — только через него)"

down:
	docker compose down

# Схема на Postgres создаётся ТОЛЬКО отсюда: автосоздание из моделей включено
# лишь для sqlite-демо. В compose это отдельный одноразовый сервис `migrate`.
migrate:
	alembic upgrade head
