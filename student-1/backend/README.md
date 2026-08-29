# Student 1 backend service

This FastAPI service exposes the public TripGenie Student 1 `/api` CRUD surface and talks to the Student 1 database service over HTTP only.

## Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `STUDENT1_BACKEND_API_PREFIX` | `/api` | Public API prefix. |
| `STUDENT1_BACKEND_DB_API_BASE_URL` | `http://student-1-database:8002` | Base URL for the internal Student 1 database API. |
| `STUDENT1_BACKEND_DB_API_PREFIX` | `/internal` | Internal Student 1 database API prefix. |
| `STUDENT1_BACKEND_DB_API_TIMEOUT_SECONDS` | `5` | Timeout for backend-to-database HTTP calls. |
| `STUDENT1_BACKEND_OLLAMA_BASE_URL` | `http://ollama:11434` when unset | Ollama runtime URL. Set it to a blank value to disable AI-mode intentionally. |
| `STUDENT1_BACKEND_OLLAMA_MODEL` | `qwen2.5:0.5b` | Default local model for runtime AI-mode. |
| `STUDENT1_BACKEND_OLLAMA_TIMEOUT_SECONDS` | `15` | Timeout for Ollama health and generate calls. |
| `STUDENT1_BACKEND_OLLAMA_MAX_RESPONSE_BYTES` | `16384` | Maximum accepted Ollama response body size. |
| `STUDENT1_BACKEND_AI_PROMPT_ASSET` | `runtime_ai_suggestions_v1.md` | Versioned runtime prompt asset loaded from `backend_service/prompts/`. |
| `STUDENT1_BACKEND_AI_MAX_ATTEMPTS` | `2` | Maximum total attempts for retryable model-output failures. |
| `STUDENT1_BACKEND_AI_MAX_CONTEXT_ITEMS` | `12` | Maximum existing itinerary items embedded in prompt context. |
| `STUDENT1_BACKEND_SERVICE_NAME` | `student-1-backend` | Service name reported by health endpoints. |

## Trip duration rule

TripGenie applies a project-specific maximum trip duration of **366 inclusive calendar days**. `POST /api/trips` and effective `PATCH /api/trips/{tripId}` payloads that exceed that limit return the normal validation envelope, and trip detail responses refuse oversized upstream records with a dependency error instead of expanding an unbounded `days` list.

## Current concurrency note

`PATCH` flows use a read-merge-write pattern against the database API so the backend can validate effective records before forwarding partial updates. The current internal API does not expose record versions or conditional writes, so concurrent updates are still last-write-wins across services; the backend re-reads committed state after writes and the database API remains the final validation guard.

## Runtime AI-mode

- `POST /api/trips/{tripId}/ai-suggestions` now calls Ollama asynchronously, requires structured output, validates returned drafts against the same itinerary rules, and never persists them automatically.
- Returned suggestions always include `persisted=false` and `approval_required=true`.
- Retry/adaptation is limited to correctable parse/schema/constraint failures only and is a TripGenie runtime robustness feature, **not** the assessed course `Plan -> Act -> Observe -> Adapt` workflow.
- `GET /health` may report a degraded Ollama dependency while `GET /ready` still depends on database readiness only, so CRUD remains available when Ollama is down.
- The runtime prompt asset is versioned at `backend_service/prompts/runtime_ai_suggestions_v1.md`; implementation notes live in `docs/architecture/student-1-runtime-ai-mode.md`.
