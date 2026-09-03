FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DATABASE_URL=sqlite:////data/student-4/activities.db \
    SEED_DATA=1

WORKDIR /app

RUN addgroup --system tripgenie \
    && adduser --system --ingroup tripgenie --home /nonexistent tripgenie \
    && mkdir -p /data/student-4

COPY database/pyproject.toml ./pyproject.toml
COPY database/student4_database_service ./student4_database_service

RUN python -m pip install --upgrade pip \
    && python -m pip install . \
    && chown -R tripgenie:tripgenie /app /data/student-4

USER tripgenie

EXPOSE 8009

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8009/internal/health', timeout=2)"]

CMD ["uvicorn", "student4_database_service.app:app", "--host", "0.0.0.0", "--port", "8009"]
