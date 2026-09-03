FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DATABASE_URL=http://shared-database:9101 \
    DB_TIMEOUT=5

WORKDIR /app

RUN addgroup --system tripgenie \
    && adduser --system --ingroup tripgenie --home /nonexistent tripgenie

COPY backend/pyproject.toml ./pyproject.toml
COPY backend/shared_backend_service ./shared_backend_service

RUN python -m pip install --upgrade pip \
    && python -m pip install .

RUN chown -R tripgenie:tripgenie /app

EXPOSE 9100

USER tripgenie

CMD ["uvicorn", "shared_backend_service.app:app", "--host", "0.0.0.0", "--port", "9100"]
