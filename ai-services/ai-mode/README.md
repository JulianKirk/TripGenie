# TripGenie shared AI-Mode service

This service provides the shared Release 0 runtime boundary between TripGenie student backends and Ollama.

- Runtime: FastAPI on Python 3.11
- Official provider dependency: `ollama==0.6.2`
- Scope: single-shot bounded generation only
- Out of scope: streaming, chat sessions, memory, tools, MCP, RAG, multi-agent orchestration

Student backends must render their own prompts, own domain retries/validation, and keep human approval/persistence rules outside this service.

## Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `AI_MODE_SERVICE_NAME` | `ai-mode` | Service name reported by health endpoints. |
| `AI_MODE_OLLAMA_BASE_URL` | `http://ollama:11434` | Ollama base URL used only by this shared service. |
| `AI_MODE_DEFAULT_MODEL` | `qwen2.5:0.5b` | Default approved model used when callers do not request an override. |
| `AI_MODE_ALLOWED_MODELS` | `qwen2.5:0.5b,llama3.1:8b` | Allowlist of approved runtime models. Arbitrary provider model names are rejected. |
| `AI_MODE_TIMEOUT_SECONDS` | `15` | Timeout for Ollama list/generate calls. |
| `AI_MODE_MAX_PROMPT_CHARS` | `12000` | Max accepted rendered prompt length. |
| `AI_MODE_MAX_SCHEMA_CHARS` | `8000` | Max accepted JSON-schema serialized length. |
| `AI_MODE_MAX_RESPONSE_BYTES` | `16384` | Max accepted provider response size. |

## Public API

### `GET /health`

- Returns `200`
- Reports overall service status plus Ollama dependency status
- `status=degraded` when Ollama is unavailable, invalid, or missing the configured model

Example:

```json
{
  "data": {
    "status": "ok",
    "service": "ai-mode",
    "dependencies": {
      "ollama": {
        "status": "ok",
        "service": "ollama",
        "detail": "Ollama responded successfully and the configured model is available.",
        "code": null
      }
    }
  }
}
```

### `GET /ready`

- Returns `200` when the shared service can generate with its configured/default model
- Returns `503` when the provider is unavailable or the configured model is missing

### `POST /generate`

Single-shot non-stream generation only.

Request:

```json
{
  "prompt": "Return JSON only for this trip-planning request.",
  "model": "qwen2.5:0.5b",
  "schema": {
    "type": "object",
    "properties": {
      "suggestions": {
        "type": "array"
      }
    },
    "required": ["suggestions"]
  },
  "correlation_id": "trip_ai_20270402",
  "metadata": {
    "feature": "student-1-trip-suggestions",
    "trip_id": "trip_2027_sydney_getaway",
    "attempt": "1"
  }
}
```

Response:

```json
{
  "data": {
    "run_id": "aimode_1234abcd5678",
    "correlation_id": "trip_ai_20270402",
    "model": "qwen2.5:0.5b",
    "provider": "ollama",
    "response": "{\"suggestions\":[]}",
    "done": true
  }
}
```

## Stable errors

The service normalizes provider failures into bounded envelopes.

### Validation error

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "One or more fields failed validation.",
    "details": [
      {
        "field": "model",
        "issue": "must be one of: qwen2.5:0.5b, llama3.1:8b"
      }
    ]
  }
}
```

### Provider unavailable or timeout

```json
{
  "error": {
    "code": "DEPENDENCY_UNAVAILABLE",
    "message": "The AI provider is unavailable.",
    "details": [
      {
        "field": "ai_mode",
        "issue": "provider connection failed"
      }
    ]
  }
}
```

```json
{
  "error": {
    "code": "DEPENDENCY_TIMEOUT",
    "message": "The AI provider did not respond before the configured timeout.",
    "details": [
      {
        "field": "ai_mode",
        "issue": "provider request timed out"
      }
    ]
  }
}
```

### Model unavailable

```json
{
  "error": {
    "code": "MODEL_UNAVAILABLE",
    "message": "Requested AI model is not available.",
    "details": [
      {
        "field": "model",
        "issue": "model 'llama3.1:8b' is not available in Ollama"
      }
    ]
  }
}
```

### Malformed or oversized provider response

```json
{
  "error": {
    "code": "BAD_GATEWAY",
    "message": "The AI provider returned a malformed generate response.",
    "details": [
      {
        "field": "ai_mode",
        "issue": "provider response body was malformed"
      }
    ]
  }
}
```

```json
{
  "error": {
    "code": "DEPENDENCY_RESPONSE_TOO_LARGE",
    "message": "The AI provider returned a response that exceeded the configured size limit.",
    "details": [
      {
        "field": "ai_mode",
        "issue": "provider response exceeded 16384 bytes"
      }
    ]
  }
}
```

## Consumer guidance for Students 2-5

Student backends should treat this service as a thin generation dependency.

### Recommended environment-variable pattern

| Consumer | Base URL variable | Timeout variable |
| --- | --- | --- |
| Student 1 | `STUDENT1_BACKEND_AI_MODE_BASE_URL` | `STUDENT1_BACKEND_AI_MODE_TIMEOUT_SECONDS` |
| Student 2 | `STUDENT2_BACKEND_AI_MODE_BASE_URL` | `STUDENT2_BACKEND_AI_MODE_TIMEOUT_SECONDS` |
| Student 3 | `STUDENT3_BACKEND_AI_MODE_BASE_URL` | `STUDENT3_BACKEND_AI_MODE_TIMEOUT_SECONDS` |
| Student 4 | `STUDENT4_BACKEND_AI_MODE_BASE_URL` | `STUDENT4_BACKEND_AI_MODE_TIMEOUT_SECONDS` |
| Student 5 | `STUDENT5_BACKEND_AI_MODE_BASE_URL` | `STUDENT5_BACKEND_AI_MODE_TIMEOUT_SECONDS` |

### Backend responsibilities that remain outside this service

- render the full prompt for the relevant domain feature
- define any domain output schema
- validate generated content against business rules
- decide whether and when to retry correctable domain failures
- enforce `persisted=false` / `approval_required=true` or equivalent approval rules

### Minimal consumer example

See [`examples/python_httpx_consumer.py`](./examples/python_httpx_consumer.py) for an async `httpx` pattern.

## Logging and privacy

The service logs safe metadata only:

- stage
- run ID
- correlation ID
- model
- prompt/schema lengths
- metadata count
- error code

It must not log full prompts, raw user context, or raw provider output.

## Docker and Compose expectation

The Docker image is built from [`Dockerfile`](./Dockerfile) and exposes port `8006`.

Issue #13 owns final Compose wiring. The expected runtime contract is:

- service name: `ai-mode`
- backend-to-service URL: `http://ai-mode:8006`
- service-to-provider URL: `http://ollama:11434`

This README documents the contract only; it does not require Compose changes in this PR.
