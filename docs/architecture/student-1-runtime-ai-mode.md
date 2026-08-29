# Student 1 Runtime AI-Mode Contract and Implementation Notes

Related architecture: [Student 1 Release 0 architecture, runtime modes, and decision traceability](./student-1-release-0-architecture.md)  
Related ADR: [ADR-0002](./decisions/0002-student-1-internal-api-and-observability.md)  
Runtime prompt asset: [`student-1/backend/backend_service/prompts/runtime_ai_suggestions_v1.md`](../../student-1/backend/backend_service/prompts/runtime_ai_suggestions_v1.md)

## 1. Scope and boundary

This document describes the **implemented Student 1 runtime AI-mode** added for issue #12.

- It covers the end-user suggestion flow: **frontend -> backend -> Ollama -> approved local model**.
- It does **not** relabel runtime retries as the course-assessed `Plan -> Act -> Observe -> Adapt` workflow.
- It keeps Release 0 scope bounded to local Ollama suggestions for trip and itinerary planning only.
- MCP, RAG, multi-agent runtime behaviour, and later-lab DeepSeek reasoning scope remain out of scope.

## 2. Public backend contract

### 2.1 Request

`POST /api/trips/{trip_id}/ai-suggestions`

| Field | Type | Rules |
| --- | --- | --- |
| `requested_date` | ISO date string | Required, must stay within the trip window, and all returned suggestions must use this exact date. |
| `goal` | string | Required user goal/request for the selected day. |
| `interests` | string \| null | Optional preferences, bounded before prompt construction. |
| `constraints` | string \| null | Optional practical constraints, bounded before prompt construction. |

### 2.2 Response

The endpoint returns **drafts only** and never writes itinerary items directly.

| Field | Meaning |
| --- | --- |
| `trip_id` | Trip being planned. |
| `requested_date` | Date used for generation and validation. |
| `model` | Configured Ollama model name. |
| `prompt_asset` | Versioned runtime prompt asset used for the call. |
| `run_id` | Per-request runtime identifier for report/evidence hooks. |
| `correlation_id` | Correlation identifier echoed/generated for logs and troubleshooting. |
| `attempt_count` | Total Ollama attempts used before returning a terminal outcome. |
| `persisted` | Always `false`. |
| `approval_required` | Always `true`. |
| `suggestions[]` | Draft itinerary items that satisfy the same date/time/category rules as normal CRUD. |

Each suggestion includes the normal itinerary fields plus optional `rationale`, and repeats:

- `persisted=false`
- `approval_required=true`

## 3. Prompt context and bounding rules

The backend builds bounded prompt context from:

- trip destination
- trip start and end dates
- traveller count
- a truncated trip notes excerpt
- requested planning date
- user `goal`
- optional `interests`
- optional `constraints`
- bounded existing itinerary context

Existing itinerary context is deliberately capped so prompts do not grow without limit:

- items are prioritised by the requested date first, then by closeness to that date
- only the configured maximum number of items is embedded in the prompt
- the context still records `total_existing_items` and `omitted_existing_items`
- descriptions and notes are truncated to short excerpts before prompt assembly

## 4. Output schema and validation

Ollama receives a JSON schema in the `format` parameter and is asked to return JSON only.

The Ollama transport parser is forward-compatible with documented extra runtime metadata such as model `details`, `size`, `digest`, `modified_at`, `context`, and duration/token counters. Student 1 still validates the fields it actually consumes strictly:

- `/api/tags` must expose `models[]` with a usable `name` (or accepted legacy `model`) for model matching
- `/api/generate` must expose a terminal non-stream response with valid `response` text and `done=true`

Returned suggestions are then normalised and validated against TripGenie rules:

- requested date must remain inside the parent trip window
- each suggestion must stay on the exact requested date
- allowed categories must match Student 1 itinerary categories
- required fields must be present
- timed suggestions must keep `start_time < end_time`
- obviously duplicate suggestions are rejected
- overlapping timed suggestions are rejected when the existing rules give enough information to detect conflicts

If validation succeeds, the suggestions are sorted and returned as reviewable drafts.

## 5. Runtime retry/adaptation policy

The runtime retry path is a **robustness mechanism**, not the assessed course loop.

- Retries are limited by `STUDENT1_BACKEND_AI_MAX_ATTEMPTS` (default: `2` total attempts, allowed range: `1` to `10`).
- Only correctable model-output failures are retried:
  - invalid JSON
  - schema mismatch
  - constraint/rule failures
- The second attempt includes an adaptation note describing the prior failure class without logging or storing the raw prompt/output.
- Network failures, timeouts, malformed HTTP responses, and oversized dependency responses return explicit terminal errors immediately instead of retrying.

If the cap is exhausted, the endpoint returns `502 AI_OUTPUT_INVALID` with a stable, bounded error payload.

## 6. Stable dependency and terminal errors

| Condition | HTTP | Code | Behaviour |
| --- | --- | --- | --- |
| Ollama unavailable / not configured for runtime use | `503` | `DEPENDENCY_UNAVAILABLE` | CRUD remains usable; AI-mode call fails explicitly. |
| Ollama timeout | `504` | `DEPENDENCY_TIMEOUT` | CRUD remains usable; AI-mode call fails explicitly. |
| Malformed Ollama HTTP/JSON/schema envelope | `502` | `BAD_GATEWAY` | Returned as an explicit dependency/output failure. |
| Oversized Ollama response | `502` | `DEPENDENCY_RESPONSE_TOO_LARGE` | Returned without retry. |
| Retryable AI output still invalid after the cap | `502` | `AI_OUTPUT_INVALID` | Explicit runtime validation exhaustion. |

`GET /health` may report a degraded Ollama dependency, but `GET /ready` still depends on the database API only so normal CRUD remains available when Ollama is down. If `/ready` includes an Ollama dependency status, it is cached/non-authoritative and never comes from a live readiness-path Ollama probe.

## 7. Human approval boundary

The frontend shows AI output as draft planning advice only.

- Suggestions are never auto-persisted.
- The result cards link into the existing itinerary-item create form.
- Users review, edit, and save each draft through normal CRUD.
- There is no silent bulk-save action.

## 8. Privacy and logging

TripGenie logs stage/attempt events for runtime troubleshooting, but avoids logging:

- raw prompt bodies
- full free-text notes
- full user goal/interests/constraints text
- unbounded raw model output

Instead, logs record bounded metadata such as:

- stage name
- run ID
- correlation ID
- trip ID
- attempt number
- counts/lengths
- terminal failure class

## 9. Environment configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `STUDENT1_BACKEND_OLLAMA_BASE_URL` | `http://ollama:11434` when unset | Ollama runtime URL. Set blank to disable runtime AI-mode intentionally. |
| `STUDENT1_BACKEND_OLLAMA_MODEL` | `qwen2.5:0.5b` | Default local model for Release 0 AI-mode. |
| `STUDENT1_BACKEND_OLLAMA_TIMEOUT_SECONDS` | `15` | Timeout for Ollama generate and health calls. |
| `STUDENT1_BACKEND_OLLAMA_MAX_RESPONSE_BYTES` | `16384` | Maximum accepted Ollama response body size. |
| `STUDENT1_BACKEND_AI_PROMPT_ASSET` | `runtime_ai_suggestions_v1.md` | Versioned runtime prompt asset name. |
| `STUDENT1_BACKEND_AI_MAX_ATTEMPTS` | `2` | Maximum total attempts for retryable model-output failures. Must stay between `1` and `10`. |
| `STUDENT1_BACKEND_AI_MAX_CONTEXT_ITEMS` | `12` | Maximum existing itinerary items embedded in prompt context. |

## 10. Frontend runtime notes

The Student 1 frontend now:

- replaces the disabled placeholder with an accessible AI suggestion form
- preserves entered values on backend/model validation failures
- exposes loading, error, empty, and draft-result states through HTMX updates
- marks returned suggestions as `Draft`, `Approval required`, and `persisted=false`
- routes every save back through the existing itinerary-item CRUD form

## 11. Evidence hooks for the report

This implementation adds honest evidence hooks without claiming showcase evidence that has not been run:

- versioned prompt asset path
- runtime `run_id`
- runtime `correlation_id`
- configured model name
- attempt count
- explicit health/dependency states

These are suitable to reference in a report **after** live browser/HTTP/Ollama execution evidence is captured.
