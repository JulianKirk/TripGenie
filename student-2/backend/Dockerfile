FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DATABASE_URL=http://student-2-database:9001 \
    DB_TIMEOUT=5

WORKDIR /app

RUN addgroup --system tripgenie \
    && adduser --system --ingroup tripgenie --home /nonexistent tripgenie

COPY backend/pyproject.toml ./pyproject.toml
COPY backend/backend_service ./backend_service

RUN python -m pip install --upgrade pip \
    && python -m pip install .

RUN chown -R tripgenie:tripgenie /app

EXPOSE 9000

USER tripgenie

CMD ["uvicorn", "backend_service.app:app", "--host", "0.0.0.0", "--port", "9000"]
