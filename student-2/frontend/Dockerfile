FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    BACKEND_URL=http://student-2-backend:9000 \
    BACKEND_TIMEOUT=5

WORKDIR /app

RUN addgroup --system tripgenie \
    && adduser --system --ingroup tripgenie --home /nonexistent tripgenie

COPY frontend/pyproject.toml ./pyproject.toml
COPY frontend/frontend_service ./frontend_service

RUN python -m pip install --upgrade pip \
    && python -m pip install .

RUN chown -R tripgenie:tripgenie /app

EXPOSE 9003

USER tripgenie

CMD ["uvicorn", "frontend_service.app:app", "--host", "0.0.0.0", "--port", "9003"]
