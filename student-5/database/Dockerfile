FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    STUDENT5_DB_API_PREFIX=/internal \
    STUDENT5_SQLITE_PATH=/data/student-5/tripgenie.db

WORKDIR /app

RUN adduser --disabled-password --gecos "" --uid 10001 tripgenie \
    && mkdir -p /data/student-5 \
    && chown -R tripgenie:tripgenie /data/student-5

COPY database/pyproject.toml ./pyproject.toml
COPY database/student5_database_service ./student5_database_service

RUN python -m pip install --upgrade pip \
    && python -m pip install .

USER tripgenie

EXPOSE 8007

CMD ["uvicorn", "student5_database_service.app:app", "--host", "0.0.0.0", "--port", "8007"]