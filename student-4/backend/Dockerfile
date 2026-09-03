FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DATABASE_URL=http://student-4-database:8009 \
    LOCATION_URL=http://shared-backend:9100 \
    ITINERARY_URL=http://student-1-backend:8001

WORKDIR /app

RUN addgroup --system tripgenie \
    && adduser --system --ingroup tripgenie --home /nonexistent tripgenie

COPY backend/pyproject.toml ./pyproject.toml
COPY backend/student4_backend_service ./student4_backend_service

RUN python -m pip install --upgrade pip \
    && python -m pip install . \
    && chown -R tripgenie:tripgenie /app

USER tripgenie

EXPOSE 8008

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8008/health', timeout=2)"]

CMD ["uvicorn", "student4_backend_service.app:app", "--host", "0.0.0.0", "--port", "8008"]
