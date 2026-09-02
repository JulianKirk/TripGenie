FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    STUDENT5_BACKEND_API_PREFIX=/api \
    STUDENT5_BACKEND_DB_API_BASE_URL=http://student-5-database:8007

WORKDIR /app

RUN adduser --disabled-password --gecos "" --uid 10001 tripgenie

COPY backend/pyproject.toml ./pyproject.toml
COPY backend/student5_backend_service ./student5_backend_service

RUN python -m pip install --upgrade pip \
    && python -m pip install .

USER tripgenie

EXPOSE 8005

CMD ["uvicorn", "student5_backend_service.app:app", "--host", "0.0.0.0", "--port", "8005"]