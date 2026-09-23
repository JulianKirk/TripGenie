# TripGenie shared AI-Mode service

This service provides the shared runtime boundary between TripGenie services
and a host-managed Ollama runtime.

- Runtime: FastAPI on Python 3.11
- Official provider dependency: `ollama==0.6.2`
- Scope: single-shot bounded generation and embeddings
- Out of scope: streaming, chat sessions, memory, tools, retrieval/indexing,
  and multi-agent orchestration

Student backends must render their own prompts, own domain retries/validation, and keep human approval/persistence rules outside this service.

## Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `AI_MODE_SERVICE_NAME` | `ai-mode` | Service name reported by health endpoints. |
| `AI_MODE_OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Host Ollama base URL used only by this shared service. Container deployments must override this to `http://host.docker.internal:11434`. |
| `AI_MODE_DEFAULT_MODEL` | `qwen2.5:0.5b` | Default approved model used when callers do not request an override. |
| `AI_MODE_ALLOWED_MODELS` | `qwen2.5:0.5b,llama3.1:8b` | Allowlist of approved runtime models. Arbitrary provider model names are rejected. |
| `AI_MODE_DEFAULT_EMBEDDING_MODEL` | `nomic-embed-text` | Default approved embedding model. |
| `AI_MODE_ALLOWED_EMBEDDING_MODELS` | `nomic-embed-text` | Separate allowlist for embedding models. |
| `AI_MODE_TIMEOUT_SECONDS` | `15` | Timeout for Ollama list, generate, and embed calls. |
| `AI_MODE_MAX_PROMPT_CHARS` | `12000` | Max accepted rendered prompt length. Student backends should pre-budget prompts to this same contract. |
| `AI_MODE_MAX_SCHEMA_CHARS` | `8000` | Max accepted JSON-schema serialized length. |
| `AI_MODE_MAX_RESPONSE_BYTES` | `16384` | Max accepted provider response size. |
| `AI_MODE_MAX_EMBED_INPUTS` | `32` | Maximum texts accepted by one embedding request. |
| `AI_MODE_MAX_EMBED_INPUT_CHARS` | `12000` | Maximum characters in each embedding input. |
| `AI_MODE_MAX_EMBED_DIMENSIONS` | `4096` | Maximum accepted provider vector dimension. |

## Host Ollama prerequisite

TripGenie assumes Ollama is installed and managed on the **host machine**, not
inside Docker.

1. Install Ollama on the host OS using the official installer/package for that platform.
2. Start Ollama so the shared AI-Mode service can reach its HTTP API.
   - Native `ai-mode` runs use the default `AI_MODE_OLLAMA_BASE_URL=http://127.0.0.1:11434`.
   - Containerized `ai-mode` runs receive `AI_MODE_OLLAMA_BASE_URL=http://host.docker.internal:11434` from Compose.
3. Pull the approved chat and embedding models on the host:

   ```bash
   ollama pull qwen2.5:0.5b
   ollama pull nomic-embed-text
   ```

4. Verify the host runtime before exercising the shared service:

   ```bash
   curl http://127.0.0.1:11434/api/tags
   ```

Platform notes:

- Windows/macOS native runs can use the loopback default above.
- When `ai-mode` itself runs in Docker, Compose must bridge the container to the host Ollama runtime with `host.docker.internal`; the application code does not bootstrap that alias.
- Tests and CI in this repository use mocked provider transports only. They do **not** install, start, or download Ollama/models.

## Public API

### `GET /health`

- Returns `200`
- Reports overall service status plus Ollama dependency status
- `status=degraded` when Ollama is unavailable, invalid, or missing either
  configured default model

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
        "detail": "Ollama responded successfully and the configured models are available.",
        "code": null
      }
    }
  }
}
```

### `GET /ready`

- Returns `200` when the configured/default chat and embedding models are
  available
- Returns `503` when the provider is unavailable or either model is missing

### `POST /generate`

Single-shot non-stream generation only.

`correlation_id` must be a safe single-line value that starts with a letter or digit, uses only letters, digits, `.`, `_`, `:`, or `-`, and stays within 64 characters.

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

The shared response envelope keeps the approved requested model authoritative. If provider success metadata reports a blank, invalid, or unexpected model name, that provider field is not passed through to consumers.

### `POST /embed`

Creates bounded embeddings for the shared RAG service. Chat and embedding
model allowlists are independent.

Request:

```json
{
  "inputs": [
    "First bounded source chunk",
    "Second bounded source chunk"
  ],
  "model": "nomic-embed-text",
  "correlation_id": "rag-ingest-01",
  "metadata": {
    "feature": "shared-rag"
  }
}
```

Response:

```json
{
  "data": {
    "run_id": "aimode_1234abcd5678",
    "correlation_id": "rag-ingest-01",
    "model": "nomic-embed-text",
    "provider": "ollama",
    "dimension": 768,
    "embeddings": [[0.1, 0.2], [0.3, 0.4]]
  }
}
```

AI-Mode rejects mismatched vector counts, inconsistent or excessive
dimensions, non-finite values, unavailable models, provider timeouts, and
malformed responses.

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

Generic provider `404` responses that do **not** explicitly describe a missing model are treated as provider/base-path failures, not as `MODEL_UNAVAILABLE`.

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
Correlation IDs and other logged fields are sanitized defensively to stay single-line.

## Runtime expectation

The existing Docker image supports the Release 0 Compose stack. Release 1 RAG
uses AI-Mode as a host process and does not add AI-Mode, RAG, or Ollama to
Compose.

Host start:

```bash
uv sync --extra dev
uv run uvicorn ai_mode_service.app:app --host 127.0.0.1 --port 8006
```

For a Docker consumer, bind deliberately to a host interface reachable through
`host.docker.internal`, for example `--host 0.0.0.0`, and keep port `8006`
blocked from untrusted networks. Native-only use should retain the loopback
binding.

The Release 0 Compose runtime contract remains:

- service name: `ai-mode`
- backend-to-service URL:
  - native runs: leave `STUDENT1_BACKEND_AI_MODE_BASE_URL` unset unless you are pointing at a manually started reachable `ai-mode` endpoint
  - Compose/container deployment: `http://ai-mode:8006`
- service-to-provider URL:
  - native `ai-mode`: `http://127.0.0.1:11434`
  - containerized `ai-mode`: `http://host.docker.internal:11434`

Ollama remains a host prerequisite; Compose and CI do not install, start, or download Ollama or its models.
