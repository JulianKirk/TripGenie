FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    BACKEND_URL=http://student-4-backend:8008 \
    BACKEND_TIMEOUT=5 \
    AI_TIMEOUT=210

WORKDIR /app

RUN adduser --disabled-password --gecos "" --uid 10001 tripgenie

COPY frontend/pyproject.toml ./pyproject.toml
COPY frontend/student4_frontend_service ./student4_frontend_service

RUN python -m pip install --upgrade pip \
    && python -m pip install . \
    && rm -rf /root/.cache/pip

USER tripgenie

EXPOSE 8084

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8084/ready', timeout=2)"]

CMD ["uvicorn", "student4_frontend_service.app:app", "--host", "0.0.0.0", "--port", "8084"]
