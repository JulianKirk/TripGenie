FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    STUDENT1_BACKEND_API_PREFIX=/api \
    STUDENT1_BACKEND_DB_API_BASE_URL=http://student-1-database:8002 \
    STUDENT1_BACKEND_DB_API_PREFIX=/internal \
    STUDENT1_BACKEND_DB_API_TIMEOUT_SECONDS=5

WORKDIR /app

RUN addgroup --system tripgenie \
    && adduser --system --ingroup tripgenie --home /nonexistent tripgenie

COPY backend/pyproject.toml ./pyproject.toml
COPY backend/backend_service ./backend_service

RUN python -m pip install --upgrade pip \
    && python -m pip install .

RUN chown -R tripgenie:tripgenie /app

EXPOSE 8001

USER tripgenie

CMD ["uvicorn", "backend_service.app:app", "--host", "0.0.0.0", "--port", "8001"]
