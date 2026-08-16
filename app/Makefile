.PHONY: help install dev seed test lint types up down migrate

help:
	@echo "install  — зависимости backend + frontend"
	@echo "dev      — API на 8000 и веб на 5173 (демо-БД sqlite)"
	@echo "seed     — демо-данные: 6 пациентов с полным протоколом"
	@echo "test     — pytest, вся таблица приёмки §16"
	@echo "lint     — ruff + mypy по чистому домену"
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
	ruff check packages apps
	mypy packages/domain

up:
	docker compose up --build -d
	@echo "веб http://localhost:8080 · API http://localhost:8000/docs"

down:
	docker compose down

migrate:
	alembic upgrade head
