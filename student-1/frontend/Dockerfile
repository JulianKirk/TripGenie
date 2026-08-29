FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN adduser --disabled-password --gecos "" --uid 10001 tripgenie

COPY frontend ./frontend

RUN python -m pip install --upgrade pip \
    && python -m pip install ./frontend \
    && rm -rf /root/.cache/pip

USER tripgenie

EXPOSE 8081

CMD ["uvicorn", "frontend_service.app:app", "--host", "0.0.0.0", "--port", "8081"]
