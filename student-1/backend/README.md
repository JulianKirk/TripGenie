# Student 1 backend service

This FastAPI service exposes the public TripGenie Student 1 `/api` CRUD surface and talks to the Student 1 database service over HTTP only.

## Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `STUDENT1_BACKEND_API_PREFIX` | `/api` | Public API prefix. |
| `STUDENT1_BACKEND_DB_API_BASE_URL` | `http://student-1-database:8002` | Base URL for the internal Student 1 database API. |
| `STUDENT1_BACKEND_DB_API_PREFIX` | `/internal` | Internal Student 1 database API prefix. |
| `STUDENT1_BACKEND_DB_API_TIMEOUT_SECONDS` | `5` | Timeout for backend-to-database HTTP calls. |
| `STUDENT1_BACKEND_AI_MODE_BASE_URL` | blank / disabled when unset | Shared Release 0 AI-Mode base URL. Leave unset for native runs; `docker-compose.yml` injects `http://ai-mode:8006`. |
| `STUDENT1_BACKEND_AI_MODE_TIMEOUT_SECONDS` | `15` | Timeout for backend-to-shared-AI-Mode HTTP calls. |
| `STUDENT1_BACKEND_AI_MODE_MAX_PROMPT_CHARS` | `12000` | Consumer-side prompt budget. Keep it aligned with the shared `AI_MODE_MAX_PROMPT_CHARS` contract. |
| `STUDENT1_BACKEND_AI_PROMPT_ASSET` | `runtime_ai_suggestions_v2.md` | Versioned runtime prompt asset loaded from `backend_service/prompts/`. |
| `STUDENT1_BACKEND_AI_MAX_ATTEMPTS` | `2` | Maximum total attempts for retryable model-output failures. Must stay between `1` and `10`. |
| `STUDENT1_BACKEND_AI_MAX_CONTEXT_ITEMS` | `12` | Maximum existing itinerary items embedded in prompt context. |
| `STUDENT1_BACKEND_AI_MAX_CONTEXT_ACCOMMODATIONS` | `6` | Maximum selected accommodation records embedded in prompt context. Must stay between `1` and `50`. |
| `STUDENT1_BACKEND_AI_MAX_CONTEXT_ACTIVITIES` | `12` | Maximum selected activity records embedded in prompt context. Must stay between `1` and `50`. |
| `STUDENT1_BACKEND_AI_MAX_CONTEXT_TRANSPORT` | `8` | Maximum selected transport records embedded in prompt context. Must stay between `1` and `50`. |
| `STUDENT1_BACKEND_SERVICE_NAME` | `student-1-backend` | Service name reported by health endpoints. |
| `STUDENT1_BACKEND_ACTIVITY_API_BASE_URL` | `http://student-4-backend:8008` | Student 4 public API used to enrich activity selections. |
| `STUDENT1_BACKEND_ACTIVITY_API_TIMEOUT_SECONDS` | `5` | Student 4 lookup timeout. |
| `STUDENT1_BACKEND_RAG_ENABLED` | `false` | Enables `POST /api/trips/{tripId}/rag-query`. Compose turns it on; CI and plain local runs leave it off. |
| `STUDENT1_BACKEND_RAG_BASE_URL` | `http://127.0.0.1:8011` | Shared host-run RAG server. |
| `STUDENT1_BACKEND_RAG_TIMEOUT_SECONDS` | `130` | RAG query timeout (retrieval plus generation). |
| `STUDENT1_BACKEND_MCP_ENABLED` | `false` | Enables `POST /api/trips/{tripId}/mcp-options`. |
| `STUDENT1_BACKEND_MCP_BASE_URL` | `http://127.0.0.1:8012/mcp` | Shared host-run MCP server's streamable-HTTP endpoint. |
| `STUDENT1_BACKEND_MCP_TIMEOUT_SECONDS` | `40` | Timeout per MCP tool call. |

## Activities on a trip

Activities use the same many-to-many ownership pattern as accommodations. The
Student 1 database owns `trip_activities`; Student 4 calls these public routes
and never accesses that table directly.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/trips/{tripId}/activities` | Stored activity selections for one trip. |
| `PUT` | `/api/trips/{tripId}/activities/{activityId}` | Add or replace a selection. |
| `DELETE` | `/api/trips/{tripId}/activities/{activityId}` | Remove a selection. |
| `GET` | `/api/activities/{activityId}/trips` | Reverse lookup for itinerary pickers. |

The optional `PUT` body contains `date` and `start_time`. A bodyless request
defaults to the trip's start date. The date must fall inside the trip window.
`GET /api/trips/{tripId}` includes `activities`, enriching each stored selection
with Student 4's `name`, exact `price`, `pricing_basis`, and
`duration_minutes`. Those four fields become `null` if Student 4 is unavailable;
the trip itself still returns successfully.

## Accommodations on a trip

A trip holds many accommodations and an accommodation sits on many trips, so the
link is its own table (`trip_accommodations`) rather than a column on either
side. This service owns it; the accommodation service (student 2) reads and
writes it over these four endpoints, and nothing else reaches the table.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/trips/{tripId}/accommodations` | The accommodations pinned to one trip. |
| `PUT` | `/api/trips/{tripId}/accommodations/{accommodationId}` | Pin one, for a stay window. Replaces an existing pin. |
| `DELETE` | `/api/trips/{tripId}/accommodations/{accommodationId}` | Unpin one. `404` if it was never pinned. |
| `GET` | `/api/accommodations/{accommodationId}/trips` | The reverse lookup: every trip holding one accommodation. |

`PUT` rather than `POST` because pinning the same accommodation twice must not be
a conflict. It *replaces* the pin rather than creating a second one, so
re-sending the same body changes nothing and sending different dates moves the
stay — a user correcting the dates they just entered has to see the correction
stick.

The pin records the stay window:

| Field | Required | Meaning |
| --- | --- | --- |
| `date` | No | Check-in date. Defaults to the trip's `start_date`. |
| `check_in_time` | No | Arrival time, `HH:MM`. |
| `check_out` | No | Check-out date. `null` means no departure recorded. |
| `check_out_time` | No | Departure time, `HH:MM`. |

```bash
curl -X PUT localhost:8001/api/trips/trip_2027_sydney_getaway/accommodations/acc_1 \
  -H 'Content-Type: application/json' \
  -d '{"date": "2027-04-02", "check_in_time": "15:00",
       "check_out": "2027-04-03", "check_out_time": "10:00"}'
```

The body is optional in full: without one the pin lands on the trip's first day
with no departure, which is all this endpoint could record before stay dates
existed. Both dates must fall inside the trip's own window and `check_out` may
not precede `date`; either mistake is the normal `422` validation envelope with
the offending field named. `GET /api/trips/{tripId}` returns the pins on the trip
detail as `accommodations`.

`date` is the check-in and kept its name from when it was the only date there
was; renaming it is a SQLite table rebuild for no user-visible gain.

The reverse lookup exists so a caller asking "which trips already hold this
accommodation?" makes one request rather than one per trip.

An `accommodationId` is minted by the accommodation service, so this service
validates it as a bounded `[A-Za-z0-9_-]` string rather than as a UUID — it
should not need changing when another service changes how it mints identifiers.

## Accommodation names and prices

A trip stores an accommodation's id and the stay; the name and the nightly rate
belong to **student 2**. `GET /api/trips/{tripId}` fetches them so the trip page
can show a name rather than a UUID, adding three read-only fields to each entry
in `accommodations`:

| Field | Meaning |
| --- | --- |
| `name` | Student 2's name for the accommodation |
| `price_per_night` | Its nightly rate |
| `total_price` | `price_per_night x nights`, where nights is the gap between `date` and `check_out` |

All three are `null` when student 2 cannot be reached, when it does not know the
id, or when there is nothing to multiply (no rate, or no `check_out` yet). The
trip still returns `200` — losing a name is not a reason to lose the trip. The
write endpoints are unchanged and still answer with exactly what they stored.

Configured by `STUDENT1_BACKEND_ACCOMMODATION_API_BASE_URL` (default
`http://student-2-backend:9000`) and `..._TIMEOUT_SECONDS`.

Note the two services now reference each other: student 2 calls this one to pin
accommodations to trips, and this one calls student 2 for the labels. That is a
runtime lookup in both directions, not a boot order, so `docker-compose.yml`
deliberately declares no `depends_on` from here to student 2 — it would be a
cycle compose refuses to start.

## Error responses

Every error, whatever the status, is the same envelope:

```json
{"error": {"code": "...", "message": "...", "details": [{"field": "...", "issue": "..."}]}}
```

The status distinguishes *what kind* of thing went wrong, and the two 4xx
validation codes are deliberately different conditions rather than two spellings
of one:

| Status | `code` | Raised when |
| --- | --- | --- |
| 400 | `BAD_REQUEST` | The request carries something this endpoint does not accept **at all** — an unknown query parameter. Each offending name is listed in `details`. |
| 422 | `VALIDATION_ERROR` | A value the endpoint *does* accept failed its constraints — a path id that does not match its pattern, or a body field out of range. |
| 404 | `NOT_FOUND` | The id was well-formed but nothing has it. |
| 502 | `BAD_GATEWAY` | A service behind this one answered with something unusable. |
| 503 | `DEPENDENCY_UNAVAILABLE` / `DEPENDENCY_TIMEOUT` | A service behind this one could not be reached in time. |

So `GET /api/trips/bad!id` is a `422` (the id is a value that failed a pattern)
while `GET /api/trips?bogus=1` is a `400` (there is no `bogus` parameter to
validate). Endpoints declare their own allowed parameters; anything else is
rejected rather than ignored, so a typo in a filter name is a loud error instead
of a silently unfiltered list.

## Trip duration rule

TripGenie applies a project-specific maximum trip duration of **366 inclusive calendar days**. `POST /api/trips` and effective `PATCH /api/trips/{tripId}` payloads that exceed that limit return the normal validation envelope, and trip detail responses refuse oversized upstream records with a dependency error instead of expanding an unbounded `days` list.

## Current concurrency note

`PATCH` flows use a read-merge-write pattern against the database API so the backend can validate effective records before forwarding partial updates. The current internal API does not expose record versions or conditional writes, so concurrent updates are still last-write-wins across services; the backend re-reads committed state after writes and the database API remains the final validation guard.

## Runtime AI-mode

- `POST /api/trips/{tripId}/ai-suggestions` now calls the shared `ai-mode` service asynchronously, validates returned drafts against the same itinerary rules, and never persists them automatically.
- Student 1 still owns prompt rendering, bounded trip/itinerary context, domain retry/adaptation, draft-only responses, and the human approval boundary.
- AI prompt context also includes bounded local accommodation, selected activity, and transport associations enriched through the existing Student 2, 4, and 3 HTTP clients. `source_status` distinguishes `available`, `partial`, and `unavailable` enrichment while retaining opaque IDs and authoritative local dates/times. Unknown enrichment never implies free time or availability.
- Cross-service records are prioritised and capped before HTTP fan-out. Student 1 pre-budgets prompts against the shared 12,000-character contract, compacts JSON rendering, drops optional excerpts/interests deterministically, then drops lower-priority transport, accommodation, and activity records before lower-priority ordinary itinerary items. Omitted counts and `budget_adjustments` make every reduction explicit; explicit user constraints are never silently removed.
- The shared AI-Mode service owns the official `ollama==0.6.2` client, provider configuration, approved model allowlist, provider health/readiness, safe output bounds, and normalized provider errors while targeting a host-managed Ollama runtime (`http://127.0.0.1:11434` natively or `http://host.docker.internal:11434` when the shared service runs in Docker).
- Returned suggestions always include `persisted=false` and `approval_required=true`.
- Retry/adaptation is limited to correctable parse/schema/constraint failures only and is a TripGenie runtime robustness feature, **not** the assessed course `Plan -> Act -> Observe -> Adapt` workflow.
- `GET /health` may report a degraded shared AI-Mode dependency, while `GET /ready` remains database-only and never waits on AI-mode.
- Correlation IDs are validated to safe single-line values before they are echoed or logged.
- The runtime prompt asset is versioned at `backend_service/prompts/runtime_ai_suggestions_v2.md`, validated at startup, and treats all downstream/user strings as untrusted data that cannot override instructions. Rendering replaces template placeholders in one pass so placeholder-like text inside context is never recursively expanded. It must stay inside `backend_service/prompts/`; implementation notes live in `docs/architecture/student-1-runtime-ai-mode.md`.

Shared AI-Mode generation may execute MCP tools. Automatic answer-repair retries
stop when the returned run contains tool calls, to avoid replaying actions.

## Release 1 RAG and MCP

Both routes are off unless enabled (above). Disabled returns `503` with
`RAG_DISABLED` / `MCP_DISABLED`, never an empty success. `/health` and `/ready`
never probe RAG or MCP. Each request generates one correlation id
(`student1-rag-…` / `student1-mcp-…`), sent as `correlation_id` and
`X-Request-ID`. An unknown trip is the usual `404 NOT_FOUND`.

### `POST /api/trips/{tripId}/rag-query`

Body `{"question": "What limits apply to itinerary items?"}` (1–2,000
characters after trimming, else `422 VALIDATION_ERROR`). Queries RAG with
`feature="student-1"` and returns the answer unchanged apart from validation:

```json
{"data": {"trip_id": "trip_...", "answer": "...", "confidence_category": "high",
  "insufficient_context": false,
  "citations": [{"source_id": "...", "title": "...", "section": "...", "path": "...", "chunk_id": "...", "excerpt": "..."}],
  "retrieval": {"requested_top_k": 5, "returned_chunks": 3, "maximum_score": 0.84},
  "run_id": "...", "correlation_id": "student1-rag-..."}}
```

`insufficient_context: true` comes with `confidence_category:
"insufficient_context"` and no citations. Errors: `503 INDEX_NOT_READY`,
`503 DEPENDENCY_UNAVAILABLE`, `504 DEPENDENCY_TIMEOUT` (preserved from RAG or
raised on connect failure/timeout), `502 BAD_GATEWAY` for any response that
breaks the RAG contract.

### `POST /api/trips/{tripId}/mcp-options`

Optional body `{"country": "Australia"}` (1–100 characters). Read-only option
discovery through the shared MCP tools; **nothing is persisted** — users add
options through the existing itinerary, accommodation and activity routes.

Location: a `"City, Country"` destination is split on its last comma;
otherwise the destination is the city and `country` comes from the body. The
body's country is ignored when the destination already names one.

Tools run sequentially, each with `limit=5`: `trip_get_context`,
`accommodations_search` and `activities_search` (both `skipped` without a
country), `transport_search` (destination = city) and `budgets_list`.
`budgets_get_summary` is deliberately not called: it fans out to Students 2–4
and back to this service. `trip_get_context` makes the MCP server call back
into `GET /api/trips/{tripId}`; the route handlers are sync, so that callback
runs on another threadpool worker of the same uvicorn process.

```json
{"data": {"trip_id": "trip_...", "correlation_id": "student1-mcp-...",
  "location": {"city": "Sydney", "country": "Australia"}, "persisted": false,
  "results": [
    {"tool": "trip_get_context", "arguments": {"trip_id": "trip_..."}, "status": "ok",
     "data": {"id": "trip_..."}, "error": null, "reason": null, "correlation_id": "student1-mcp-..."},
    {"tool": "accommodations_search", "arguments": {"country": "Australia", "city": "Sydney", "limit": 5},
     "status": "error", "data": null,
     "error": {"code": "PROVIDER_UNAVAILABLE", "message": "Provider failed", "retryable": true},
     "reason": null, "correlation_id": null}
  ],
  "summary": {"ok": 4, "error": 1, "skipped": 0}}}
```

One tool failing (tool error, timeout, malformed result) is recorded against
that tool and the rest still run. Per-tool error codes are the MCP tool's own
(`NOT_FOUND`, `PROVIDER_UNAVAILABLE`, …) or `DEPENDENCY_TIMEOUT`,
`DEPENDENCY_UNAVAILABLE`, `BAD_GATEWAY` (malformed), `MCP_TOOL_ERROR`
(rejected call). If **every** attempted tool failed because the MCP server
could not be reached or timed out, the route returns
`503 DEPENDENCY_UNAVAILABLE` with one `details` entry per tool instead.
