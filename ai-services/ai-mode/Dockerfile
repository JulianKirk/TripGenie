FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    AI_MODE_OLLAMA_BASE_URL=http://ollama:11434 \
    AI_MODE_DEFAULT_MODEL=qwen2.5:0.5b \
    AI_MODE_ALLOWED_MODELS=qwen2.5:0.5b,llama3.1:8b \
    AI_MODE_TIMEOUT_SECONDS=15 \
    AI_MODE_MAX_PROMPT_CHARS=12000 \
    AI_MODE_MAX_SCHEMA_CHARS=8000 \
    AI_MODE_MAX_RESPONSE_BYTES=16384

WORKDIR /app

RUN addgroup --system tripgenie \
    && adduser --system --ingroup tripgenie --home /nonexistent tripgenie

COPY pyproject.toml ./pyproject.toml
COPY ai_mode_service ./ai_mode_service

RUN python -m pip install --upgrade pip \
    && python -m pip install .

RUN chown -R tripgenie:tripgenie /app

EXPOSE 8006

USER tripgenie

CMD ["uvicorn", "ai_mode_service.app:app", "--host", "0.0.0.0", "--port", "8006"]
