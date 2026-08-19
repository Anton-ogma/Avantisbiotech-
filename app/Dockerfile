# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS base
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv
RUN adduser --system --group --no-create-home app

FROM base AS deps
COPY pyproject.toml ./
# Зависимости ставятся ИЗ pyproject, а не повторяются здесь списком: два списка
# уже разошлись — boto3 значился только в pyproject, а pypdf и pillow, без
# которых не разбирается ни один печатный протокол DIERS, не значились нигде.
RUN pip install --no-cache-dir .

FROM deps AS runtime
COPY packages ./packages
COPY apps/api ./apps/api
COPY apps/worker ./apps/worker
# Миграции и их конфигурация едут в образ: сервис `migrate` в compose запускает
# `alembic upgrade head` этим же образом, и без них он не найдёт ни ini, ни
# ревизий.
COPY db ./db
COPY alembic.ini ./alembic.ini
ENV PYTHONPATH=/srv/packages:/srv
USER app
EXPOSE 8000
HEALTHCHECK --interval=20s --timeout=4s --start-period=15s CMD \
  python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health').status==200 else 1)"
# Воркеров по числу ядер; состояние в процессе не держим — инстансы взаимозаменяемы.
CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
