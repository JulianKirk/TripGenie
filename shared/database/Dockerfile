FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DATABASE_URL=sqlite:////data/location.db

WORKDIR /app

RUN addgroup --system tripgenie \
    && adduser --system --ingroup tripgenie --home /nonexistent tripgenie \
    && mkdir -p /data

COPY database/pyproject.toml ./pyproject.toml
COPY database/shared_database_service ./shared_database_service

RUN python -m pip install --upgrade pip \
    && python -m pip install .

RUN chown -R tripgenie:tripgenie /app /data

EXPOSE 9101

USER tripgenie

CMD ["uvicorn", "shared_database_service.app:app", "--host", "0.0.0.0", "--port", "9101"]
