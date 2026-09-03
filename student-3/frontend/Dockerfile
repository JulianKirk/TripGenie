FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    STUDENT3_FRONTEND_BACKEND_BASE_URL=http://student-3-backend:8003 \
    STUDENT3_FRONTEND_BACKEND_API_PREFIX=/api \
    STUDENT3_FRONTEND_BACKEND_TIMEOUT_SECONDS=5

WORKDIR /app

RUN adduser --disabled-password --gecos "" --uid 10001 tripgenie

COPY frontend ./frontend

RUN python -m pip install --upgrade pip \
    && python -m pip install ./frontend \
    && rm -rf /root/.cache/pip

USER tripgenie

EXPOSE 8093

CMD ["uvicorn", "student3_frontend_service.app:app", "--host", "0.0.0.0", "--port", "8093"]
