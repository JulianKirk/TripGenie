FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    STUDENT5_FRONTEND_BACKEND_BASE_URL=http://student-5-backend:8005

WORKDIR /app

RUN adduser --disabled-password --gecos "" --uid 10001 tripgenie

COPY frontend/pyproject.toml ./pyproject.toml
COPY frontend/student5_frontend_service ./student5_frontend_service

RUN python -m pip install --upgrade pip \
    && python -m pip install .

USER tripgenie

EXPOSE 8085

CMD ["uvicorn", "student5_frontend_service.app:app", "--host", "0.0.0.0", "--port", "8085"]