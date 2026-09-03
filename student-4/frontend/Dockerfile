FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    BACKEND_URL=http://student-4-backend:8008 \
    BACKEND_TIMEOUT=5

WORKDIR /app

RUN adduser --disabled-password --gecos "" --uid 10001 tripgenie

COPY pyproject.toml ./pyproject.toml
COPY student4_frontend_service ./student4_frontend_service

RUN python -m pip install --upgrade pip \
    && python -m pip install . \
    && rm -rf /root/.cache/pip

USER tripgenie

EXPOSE 8084

CMD ["uvicorn", "student4_frontend_service.app:app", "--host", "0.0.0.0", "--port", "8084"]
