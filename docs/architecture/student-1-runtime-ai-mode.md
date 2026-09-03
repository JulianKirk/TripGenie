# Student 1 Runtime AI-Mode Contract and Implementation Notes

Related architecture: [Student 1 Release 0 architecture, runtime modes, and decision traceability](./student-1-release-0-architecture.md)
Shared AI-Mode contract: [`ai-services/ai-mode/README.md`](../../ai-services/ai-mode/README.md)
Related ADR: [ADR-0002](./decisions/0002-student-1-internal-api-and-observability.md)
Runtime prompt asset: [`student-1/backend/backend_service/prompts/runtime_ai_suggestions_v2.md`](../../student-1/backend/backend_service/prompts/runtime_ai_suggestions_v2.md)

## 1. Scope and boundary

This document describes the implemented **Student 1 runtime AI-mode** for issue #12.

- End-user flow is **frontend -> Student 1 backend -> shared AI-Mode service -> host Ollama runtime -> approved local model**.
- Student 1 owns the public `/api/trips/{tripId}/ai-suggestions` endpoint, prompt asset, bounded trip context, itinerary validation, domain retry/adaptation, and the draft-only approval boundary.
- The shared `ai-mode` service owns the official `ollama==0.6.2` dependency, provider configuration, approved model allowlist, provider timeouts, response-size limits, request IDs, and normalized provider errors.
- Runtime retries are a robustness feature only; they are **not** the assessed course `Plan -> Act -> Observe -> Adapt` workflow.
- MCP, RAG, multi-agent behavior, long-lived chat memory, and later-lab DeepSeek runtime behavior remain out of scope.

## 2. Public Student 1 backend contract

### 2.1 Request

`POST /api/trips/{trip_id}/ai-suggestions`

| Field | Type | Rules |
| --- | --- | --- |
| `requested_date` | ISO date string | Required and must remain within the trip window. |
| `goal` | string | Required day goal/request. |
| `interests` | string \| null | Optional preferences, bounded before prompt construction. |
| `constraints` | string \| null | Optional constraints, bounded before prompt construction. |

### 2.2 Response

The endpoint returns **drafts only** and never persists itinerary items directly.

| Field | Meaning |
| --- | --- |
| `trip_id` | Trip being planned. |
| `requested_date` | Date used for generation and validation. |
| `model` | Approved model selected by the shared AI-Mode service. |
| `prompt_asset` | Versioned Student 1 runtime prompt asset used for the request. |
| `run_id` | Student 1 request identifier for evidence and troubleshooting. |
| `correlation_id` | Correlation identifier echoed/generated across Student 1 and shared AI-Mode logs. |
| `attempt_count` | Total Student 1 `/generate` attempts used before returning a terminal outcome. |
| `persisted` | Always `false`. |
| `approval_required` | Always `true`. |
| `suggestions[]` | Draft itinerary items that pass Student 1 date/time/category rules. |

Each suggestion includes the normal itinerary fields plus optional `rationale`, and repeats:

- `persisted=false`
- `approval_required=true`

## 3. Prompt context and bounding rules

Student 1 builds bounded prompt context from:

- trip destination
- trip start and end dates
- traveller count
- a truncated trip-notes excerpt
- requested planning date
- user `goal`
- optional `interests`
- optional `constraints`
- bounded existing itinerary context
- bounded selected accommodation context from Student 1 associations, enriched
  with Student 2 name/location data when available
- bounded selected activity context from Student 1 associations, enriched with
  Student 4 name, duration, and price data when available
- bounded selected transport context from Student 1 associations, enriched with
  Student 3 mode, provider, route, departure/arrival, price, and duration data
  when available

Cross-service context keeps the locally stored opaque identifier and scheduling
facts even when an external service is unavailable. `source_status` is
`available`, `partial`, or `unavailable` and describes enrichment completeness
only; it never asserts booking availability or that unknown time is free.
Missing fields remain absent rather than being fabricated. The same best-effort
HTTP clients and enrichment helpers used by trip detail perform the enrichment;
Student 1 never reads another service's database. The synchronous database
snapshot and downstream enrichment phase runs on a worker thread so slow
Student 2/3/4 responses do not block the backend event loop or unrelated
readiness and CRUD requests.

Existing itinerary context stays bounded:

- items are prioritised by requested date first, then by closeness to that date
- only the configured maximum number of items is embedded in the prompt
- `total_existing_items` and `omitted_existing_items` remain visible in the context payload
- descriptions and notes are truncated before prompt assembly
- prompt JSON is rendered compactly rather than prettified
- if the rendered prompt would exceed the shared `AI_MODE_MAX_PROMPT_CHARS` contract, Student 1 deterministically drops optional existing-item notes/descriptions, optional trip notes and interests, then lower-priority context items while recording explicit `budget_adjustments`; requested date, traveller count, goal, explicit constraints, and retained authoritative timing are not silently removed
- cross-service records have independent configured maxima (6 accommodations,
  12 activities, and 8 transport selections by default)
- local cross-service records are prioritised and capped before external HTTP
  lookups, bounding network fan-out as well as prompt size
- budget reduction drops lower-priority transport records, then accommodation
  records, then activity records before removing lower-priority ordinary
  itinerary items; total/omitted counts remain in the serialized context
- if the irreducible required context still does not fit, Student 1 returns a `422 VALIDATION_ERROR` before calling the shared AI-Mode service

All context is deterministically serialized with sorted JSON keys. The v2
prompt asset explicitly declares all downstream and user strings to be
untrusted reference data that cannot override instructions. Template
placeholders are replaced in one pass, so placeholder-like context data is not
recursively substituted. Retry context is a bounded typed JSON structure, with
retry instructions fixed in the trusted prompt asset.

## 4. Shared AI-Mode consumer contract used by Student 1

Student 1 renders the full prompt and then calls the shared service:

`POST /generate`

Student 1 sends:

- a bounded fully rendered `prompt`
- an optional approved `model` override when needed
- an optional JSON `schema`
- `correlation_id` constrained to a safe single-line identifier (`[A-Za-z0-9][A-Za-z0-9._:-]{0,63}`)
- bounded metadata such as feature name, trip ID, requested date, attempt number, and prompt asset

The shared service:

- uses the official `ollama==0.6.2` Python client
- performs a single non-streaming generation request
- enforces the approved model allowlist
- bounds prompt/schema/output sizes
- returns normalized errors without leaking provider internals

## 5. Output schema and validation ownership

The shared service validates the provider envelope it actually consumes:

- Ollama model discovery/readiness through the official client
- terminal non-stream `/generate` responses only
- bounded output size
- the approved requested model remains authoritative for the public response envelope if provider metadata is blank, invalid, or unexpected
- tolerant handling of documented extra provider metadata

Student 1 then validates the generated JSON against its own itinerary rules:

- requested date must stay inside the parent trip window
- each suggestion must remain on the exact requested date
- allowed categories must match Student 1 itinerary categories
- required fields must be present
- timed suggestions must keep `start_time < end_time`
- obvious duplicate suggestions are rejected
- overlapping timed suggestions are rejected when rules provide enough information
- selected activity intervals are enforced only when the local date/start and
  enriched authoritative duration are all available
- selected transport intervals are enforced only when authoritative departure
  and arrival timestamps are both available; cancelled transport is ignored
- cross-service interval validation uses the capped enriched snapshot before
  prompt budgeting, so a lower-priority record omitted from the rendered prompt
  still prevents a conflicting draft
- incomplete or unavailable timing never creates an inferred end time or a
  fabricated availability constraint

If validation succeeds, suggestions are sorted and returned as reviewable drafts.

## 6. Runtime retry/adaptation policy

The retry path is a **Student 1 domain robustness mechanism**, not the assessed workflow.

- Retries are limited by `STUDENT1_BACKEND_AI_MAX_ATTEMPTS` (default `2`, valid range `1` to `10`).
- Only correctable shared-output failures are retried:
  - invalid JSON content
  - schema mismatch
  - itinerary-rule/constraint failures
- Adaptation notes describe the prior failure class without logging raw prompts, full free-text notes, or raw model output.
- Shared service unavailability, timeouts, malformed dependency HTTP, model absence, and oversized provider responses are terminal and do not trigger Student 1 retries.
- Missing or unreadable prompt assets fail fast during backend startup/configuration rather than surfacing later as endpoint 500s.

If the retry cap is exhausted, Student 1 returns `502 AI_OUTPUT_INVALID`.

## 7. Stable error handling

| Condition | HTTP | Code | Behaviour |
| --- | --- | --- | --- |
| Shared AI-Mode unavailable / not configured | `503` | `DEPENDENCY_UNAVAILABLE` | CRUD remains usable; only AI-mode fails explicitly. |
| Shared AI-Mode timeout | `504` | `DEPENDENCY_TIMEOUT` | CRUD remains usable; only AI-mode fails explicitly. |
| Shared AI-Mode malformed HTTP/JSON/schema envelope | `502` | `BAD_GATEWAY` | Returned as an explicit dependency failure. |
| Shared AI-Mode reports provider response too large | `502` | `DEPENDENCY_RESPONSE_TOO_LARGE` | Returned without retry. |
| Shared AI-Mode reports approved model unavailable | `503` | `MODEL_UNAVAILABLE` | Returned explicitly without changing CRUD readiness. |
| Retryable AI output still invalid after the cap | `502` | `AI_OUTPUT_INVALID` | Explicit Student 1 validation exhaustion. |

`GET /health` may report a degraded `ai_mode` dependency, but `GET /ready` remains database-only and never waits on the shared service.

## 8. Human approval boundary

The frontend treats AI output as advisory drafts only.

- Suggestions are never auto-persisted.
- Result cards link into the existing itinerary-item create form.
- Users review, edit, and save drafts through the normal CRUD flow.
- There is no silent bulk-save path.

## 9. Privacy and logging

Student 1 keeps troubleshooting logs bounded and avoids logging:

- raw prompt bodies
- full free-text trip notes
- full user goal/interests/constraints text
- raw unbounded AI output

Instead, logs record safe metadata such as:

- stage name
- run ID
- correlation ID
- trip ID
- attempt number
- counts and lengths
- terminal failure class

## 10. Environment configuration

### Student 1 backend

| Variable | Default | Purpose |
| --- | --- | --- |
| `STUDENT1_BACKEND_AI_MODE_BASE_URL` | blank / disabled when unset | Shared AI-Mode base URL. Leave unset for native runs; `docker-compose.yml` injects `http://ai-mode:8006`. |
| `STUDENT1_BACKEND_AI_MODE_TIMEOUT_SECONDS` | `15` | Timeout for Student 1 calls to the shared AI-Mode service. |
| `STUDENT1_BACKEND_AI_MODE_MAX_PROMPT_CHARS` | `12000` | Student-side prompt budget. Keep it aligned with the shared `AI_MODE_MAX_PROMPT_CHARS` contract. |
| `STUDENT1_BACKEND_AI_PROMPT_ASSET` | `runtime_ai_suggestions_v2.md` | Versioned runtime prompt asset. |
| `STUDENT1_BACKEND_AI_MAX_ATTEMPTS` | `2` | Maximum total attempts for retryable model-output failures. |
| `STUDENT1_BACKEND_AI_MAX_CONTEXT_ITEMS` | `12` | Maximum existing itinerary items embedded in prompt context. |
| `STUDENT1_BACKEND_AI_MAX_CONTEXT_ACCOMMODATIONS` | `6` | Maximum selected accommodation records embedded in prompt context. |
| `STUDENT1_BACKEND_AI_MAX_CONTEXT_ACTIVITIES` | `12` | Maximum selected activity records embedded in prompt context. |
| `STUDENT1_BACKEND_AI_MAX_CONTEXT_TRANSPORT` | `8` | Maximum selected transport records embedded in prompt context. |

### Shared AI-Mode service

Provider/runtime configuration now lives in [`ai-services/ai-mode/README.md`](../../ai-services/ai-mode/README.md), including:

- `AI_MODE_OLLAMA_BASE_URL`
- `AI_MODE_DEFAULT_MODEL`
- `AI_MODE_ALLOWED_MODELS`
- `AI_MODE_TIMEOUT_SECONDS`
- `AI_MODE_MAX_PROMPT_CHARS`
- `AI_MODE_MAX_SCHEMA_CHARS`
- `AI_MODE_MAX_RESPONSE_BYTES`

Release 0 expects Ollama to run on the host machine. Native shared-service runs default to `AI_MODE_OLLAMA_BASE_URL=http://127.0.0.1:11434`; `docker-compose.yml` supplies `http://host.docker.internal:11434` to the containerized shared service.

## 11. Frontend runtime notes

The Student 1 frontend now:

- replaces the old disabled placeholder with an accessible AI suggestion form
- uses HTMX for loading, error, empty, and draft-result states
- preserves entered values on backend validation and dependency failures
- labels suggestions as draft-only and approval-required
- hands AI draft review off through a POST body so generated free text does not land in URLs, browser history, or access logs
- routes every save through the existing itinerary-item CRUD form

## 12. Evidence hooks for the report

This implementation adds evidence hooks without claiming unrun showcase evidence:

- versioned prompt asset path
- runtime `run_id`
- runtime `correlation_id`
- returned model name
- attempt count
- explicit dependency/health states

These are suitable report artefacts **after** live browser, HTTP, shared-service, and Ollama execution evidence is captured.
