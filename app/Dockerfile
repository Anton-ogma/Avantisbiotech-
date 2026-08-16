# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS base
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv
RUN adduser --system --group --no-create-home app

FROM base AS deps
COPY pyproject.toml ./
RUN pip install --no-cache-dir "fastapi>=0.110" "uvicorn[standard]>=0.29" "pydantic>=2.7" \
    "pydantic-settings>=2.2" "sqlalchemy>=2.0" "alembic>=1.13" "asyncpg>=0.29" "pyyaml>=6.0" \
    "python-multipart>=0.0.9" "arq>=0.26"

FROM deps AS runtime
COPY packages ./packages
COPY apps/api ./apps/api
COPY apps/worker ./apps/worker
COPY db ./db
ENV PYTHONPATH=/srv/packages:/srv
USER app
EXPOSE 8000
HEALTHCHECK --interval=20s --timeout=4s --start-period=15s CMD \
  python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health').status==200 else 1)"
# Воркеров по числу ядер; состояние в процессе не держим — инстансы взаимозаменяемы.
CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
