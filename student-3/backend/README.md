# Student 3 backend service

This FastAPI service exposes the public TripGenie Student 3 `/api` transport surface. It
talks to the Student 3 database service over HTTP only and never opens the SQLite file.

## Scope: plan records, not reservations

TripGenie does not book transport. Adding an option to a trip records a **selection** —
"this transport is part of my trip". No reservation is placed with a carrier and no payment
is taken. `estimated_cost` is a planning figure, which is what the Student 5 budget feature
consumes; it is never an amount charged.

**Selections are stored by Student 1, not here.** Which transport belongs to which trip is
the itinerary's business, exactly as it is for accommodation and activities, so this service
writes those rows through Student 1's API and keeps only the catalogue. `plan_status` is
therefore a plan state, not a carrier state:

| Value | Meaning |
| --- | --- |
| `pending` | Shortlisted, still being considered |
| `confirmed` | Committed to the itinerary |
| `cancelled` | Removed from the plan |
| `completed` | Journey taken |

## Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `STUDENT3_BACKEND_API_PREFIX` | `/api` | Public API prefix. |
| `STUDENT3_BACKEND_DB_API_BASE_URL` | `http://student-3-database:8004` | Student 3 database service. |
| `STUDENT3_BACKEND_DB_API_PREFIX` | `/internal` | Database API prefix. |
| `STUDENT3_BACKEND_DB_API_TIMEOUT_SECONDS` | `5` | Timeout for backend-to-database calls. |
| `STUDENT3_BACKEND_SERVICE_NAME` | `student-3-backend` | Name reported by health endpoints. |
| `STUDENT3_BACKEND_TRIPS_API_BASE_URL` | `http://student-1-backend:8001` | Student 1 trips API, used only by the optional trip check. |
| `STUDENT3_BACKEND_TRIPS_API_PREFIX` | `/api` | Trips API prefix. |
| `STUDENT3_BACKEND_TRIPS_API_TIMEOUT_SECONDS` | `5` | Timeout for the trip lookup. |
| `STUDENT3_BACKEND_VERIFY_TRIP_EXISTS` | `false` | Opt in to checking a trip exists before building an AI prompt for it. Selections are validated by Student 1 regardless. |
| `STUDENT3_BACKEND_CURRENCY` | `AUD` | ISO 4217 currency for transport prices and estimates. |
| `STUDENT3_BACKEND_AI_MODE_BASE_URL` | `http://ai-mode:8006` | Shared AI-Mode service. |
| `STUDENT3_BACKEND_AI_MODE_TIMEOUT_SECONDS` | `120` | Timeout for one generation. Deliberately above AI-Mode's own budget. |
| `STUDENT3_BACKEND_AI_PROMPT_ASSET` | `transport_recommendations_v1.md` | Prompt template, versioned in `student3_backend_service/prompts/`. |
| `STUDENT3_BACKEND_AI_PROMPT_MAX_CHARS` | `12000` | Prompt budget; a larger render returns `422`. |
| `STUDENT3_BACKEND_AI_MAX_CANDIDATES` | `12` | Most options ever shown to the model. |
| `STUDENT3_BACKEND_MCP_ENABLED` | `false` | Release 1 MCP lookups. Compose sets `true`; CI sets `false`. |
| `STUDENT3_BACKEND_MCP_BASE_URL` | `http://127.0.0.1:8012/mcp` | Shared host-run MCP server. Compose uses `http://host.docker.internal:8012/mcp`. |
| `STUDENT3_BACKEND_MCP_TIMEOUT_SECONDS` | `40` | Timeout for one MCP tool call. |
| `STUDENT3_BACKEND_RAG_ENABLED` | `false` | Release 1 transport guide. Compose sets `true`; CI sets `false`. |
| `STUDENT3_BACKEND_RAG_BASE_URL` | `http://127.0.0.1:8011` | Shared host-run RAG server. Compose uses `http://host.docker.internal:8011`. |
| `STUDENT3_BACKEND_RAG_TIMEOUT_SECONDS` | `130` | Timeout for one RAG query, covering retrieval and grounded generation. |

## API surface

Responses wrap payloads in a `data` envelope; failures use the shared
`{"error": {"code", "message", "details"}}` shape.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Service status plus the database dependency. Always `200`. |
| `GET` | `/ready` | `200` when the database is reachable, `503` otherwise. |
| `GET` | `/api/transport-options` | List and filter options. |
| `GET` | `/api/transport-options/compare` | Side-by-side selection, `?ids=` up to 4. |
| `POST` | `/api/transport-options` | Create an option. |
| `GET` | `/api/transport-options/{transportId}` | Fetch one option. |
| `PATCH` | `/api/transport-options/{transportId}` | Partially update an option. |
| `DELETE` | `/api/transport-options/{transportId}` | Delete an option no trip holds. |
| `GET` | `/api/transport-options/{transportId}/itineraries` | Every trip, marked where it holds this option. |
| `PUT` | `/api/transport-options/{transportId}/itineraries/{tripId}` | Add this option to a trip. |
| `DELETE` | `/api/transport-options/{transportId}/itineraries/{tripId}` | Remove it from a trip. |
| `GET` | `/api/trip-directory` | Trips available for selection, read through from Student 1. |
| `GET` | `/api/trips/{tripId}/transport` | **Composed view** — everything planned for one trip. |
| `POST` | `/api/transport-options/recommendations` | **AI mode** — advisory transport suggestions. Writes nothing. |
| `POST` | `/api/transport-options/rag-query` | **RAG** — grounded transport guidance from the shared RAG server. Writes nothing. |
| `POST` | `/api/transport-options/mcp/search` | **MCP** — `transport_search` through the shared MCP server. Writes nothing. |
| `POST` | `/api/transport-options/mcp/compare` | **MCP** — `transport_compare`. Writes nothing. |
| `POST` | `/api/trips/{tripId}/transport/mcp` | **MCP** — `transport_trip_costs`. Writes nothing. |

### Filters

`GET /api/transport-options` accepts `type`, `provider`, `origin`, `destination`,
`availability_status`, `min_price`, `max_price`, `departure_from`, `departure_to`.
Unsupported query parameters return `400` rather than being ignored, and reversed ranges
return `422`.

### `GET /api/trips/{tripId}/transport`

Composed here, from Student 1's selections joined to this service's options. Neither service
can answer it alone: Student 1 holds which transport a trip has, this service holds the route
and the price, and only this side knows whether that price is per traveller or per vehicle.

**The shape of this response is deliberately unchanged** from when the selections were stored
locally, because Student 5's budget feature reads `estimated_cost_total` and `currency` from
it and should not have to know they moved. Each selection is returned joined to its option,
ordered by departure, plus:

- `entry_count` — every entry for the trip
- `active_entry_count` — entries that still count (`pending`, `confirmed`, `completed`)
- `estimated_cost_total` — summed over active entries only, in whole cents
- `currency` — explicit ISO 4217 currency for the estimate

### `GET /api/transport-options/compare`

Accepts `?ids=a,b` or repeated `?ids=a&ids=b`, up to **4** options. Duplicates are rejected,
and an unknown identifier returns `404` rather than being silently dropped — a caller must
never be shown a shorter comparison than it asked for.

### `POST /api/transport-options/recommendations`

Advisory transport guidance from the shared AI-Mode service (which owns the
boundary to Ollama). The request takes an optional `trip_id`, `origin` and
`destination`, plus the traveller's `question`.

The response is a resolved draft, not raw model text: every suggestion comes
back as the full stored option joined to the model's reason, alongside
`advisory_only: true`, the `disclaimer`, and the `run_id`, `model` and
`provider` that produced it, so a caller can always cite the run.

**This route writes nothing.** A suggestion becomes part of a trip only when a
traveller adds it to a trip from the option's own page. That is the
human approval step, and it is the reason the model can never put a journey in
someone's itinerary by itself.

The grounding guards, in the order they apply:

1. **Bounded candidates.** Only actionable options are offered to the model —
   never `sold_out` or `cancelled`, never zero seats remaining — cheapest first
   and capped at `AI_MAX_CANDIDATES`, so a truncated list still holds the
   options most likely to matter.
2. **Prompt budget.** A render above `AI_PROMPT_MAX_CHARS` returns `422`
   `PROMPT_BUDGET_EXCEEDED` rather than being silently truncated mid-fact.
3. **Schema-checked reply.** AI-Mode is asked for JSON matching this service's
   own draft schema; an unfinished or malformed reply is `502`.
4. **Resolution against the candidate list.** An id the model was not given is
   `502` `BAD_GATEWAY` — a hallucinated identifier must never reach a
   traveller. Duplicate suggestions are collapsed rather than failing the draft.

The prompt itself is a versioned asset rather than a string in the code, so a
wording change is reviewable in a diff. It forbids inventing ids, recommending
unbookable options, recalculating `duration_minutes` (already offset-aware),
and claiming to have booked, paid for or saved anything.

When AI-Mode is unreachable the route returns `503`; browsing, comparing and
planning are unaffected, which is why the Compose dependency is
`service_started` rather than `service_healthy`.

## Release 1 MCP

Transport lookups through the **shared** host-run MCP server
(`ai-services/mcp-server`), which owns the tool definitions. This service calls
it over JSON-RPC `tools/call` on its streamable-HTTP endpoint; the browser
never reaches MCP directly.

| Route | Tool | Request body |
| --- | --- | --- |
| `POST /api/transport-options/mcp/search` | `transport_search` | `{origin?, destination?, limit?}` — `limit` 1–20, default 5 |
| `POST /api/transport-options/mcp/compare` | `transport_compare` | `{ids}` — 1–4 distinct transport ids |
| `POST /api/trips/{tripId}/transport/mcp` | `transport_trip_costs` | none |

Each returns one structured result:

```json
{"data": {"action": "search", "tool": "transport_search",
  "arguments": {"limit": 5, "destination": "Sydney"},
  "status": "ok", "data": {"items": [...], "count": 1, "truncated": false},
  "error": null, "correlation_id": "student3-mcp-3f2a9c1b7d4e",
  "duration_ms": 24, "persisted": false}}
```

Tool boundaries, in the order they apply:

1. **Allow-listed actions.** The caller picks a route, never a tool name, server
   URL or extra argument; unknown body fields and query parameters are refused.
2. **Validated before the call.** Ids must match the transport and trip patterns,
   filters are 1–255 characters and comparisons are 1–4 distinct ids, so a bad
   request is a `422` and never reaches MCP.
3. **Read-only tools only.** All four transport tools `GET` this service's public
   `/api`; `persisted` is always `false`.
4. **Bounded results.** A tool result over 32 KB, or one that does not match the
   `{ok, data}` envelope, is `502`.

A tool that ran and refused (an unknown trip, say) is `200` with
`status: "error"` and the tool's own `error.code`, so the UI can show why. The
MCP server being unreachable is `503 DEPENDENCY_UNAVAILABLE`, too slow is `504`,
and an unusable reply is `502`. When disabled, every route is
`503 MCP_DISABLED` — never an empty success — while browsing, comparing and
planning carry on. `/health` and `/ready` report
`"integrations": {"rag": "enabled" | "disabled", "mcp": "enabled" | "disabled"}`
from configuration only; they never contact the MCP or RAG server.

The handlers are synchronous on purpose. The MCP tools read this same service
back through `127.0.0.1:18003`, so the worker waiting on MCP must not block the
event loop that answers that call. Logs carry the correlation id, tool, status
and duration, never tool payloads.

## Release 1 RAG

`POST /api/transport-options/rag-query` takes only `{"question": "..."}` (1–2000
characters) and sends it to the **shared** host-run RAG server's `/query` with
`feature: "student-3"` and `top_k: 5` fixed here, so a caller can never widen
the knowledge scope. The answer is passed through unchanged:

```json
{"data": {"answer": "A cancelled transport selection does not count ...",
  "confidence_category": "high", "insufficient_context": false,
  "citations": [{"source_id": "transport-pricing-and-costs",
    "title": "Transport Pricing and Cost Estimates",
    "section": "Transport costs: the trip transport total",
    "path": "ai-services/rag-server/knowledge/transport/pricing-and-costs.md",
    "chunk_id": "...", "excerpt": "..."}],
  "retrieval": {"requested_top_k": 5, "returned_chunks": 3, "maximum_score": 0.83},
  "run_id": "...", "correlation_id": "student3-rag-3f2a9c1b7d4e"}}
```

Confidence is decided by the RAG server from retrieval scores (`high` ≥ 0.8,
`medium` ≥ 0.7, `low` ≥ 0.5). When nothing relevant is retrieved the answer is
still `200`, with `insufficient_context: true`, confidence
`insufficient_context` and no citations, rather than an unsupported answer. A
reply that contradicts itself — grounded with no citations, or insufficient
with citations — or has an unknown `schema_version` is refused as `502`.

The RAG server's own `503 INDEX_NOT_READY` / `DEPENDENCY_UNAVAILABLE` and
`504 DEPENDENCY_TIMEOUT` pass through so the UI can say why there is no answer;
anything else is `502`. When disabled the route is `503 RAG_DISABLED`. The
question and answer are never logged, only the correlation id, confidence and
citation count.

The Student 3 knowledge sources, tagged `student-3` in
`ai-services/rag-server/config/sources.json`, are this README and three curated
guides under `ai-services/rag-server/knowledge/transport/`: choosing transport,
pricing and cost estimates, and planning and availability. Each guide section
fits one retrieval chunk. Calibration cases for them are in
`config/calibration-queries.json`; rebuild the index with
`python -m rag_service ingest --rebuild` after changing any of them.

## Business rules owned here

- **Route sanity.** `origin` must differ from `destination`, checked case-insensitively.
  `car_rental` is exempt: collecting and returning a vehicle at one depot is normal. A
  `PATCH` is validated against the merged record, so it cannot collapse a route.
- **Ordered ranges.** `min_price` above `max_price`, or `departure_from` after
  `departure_to`, returns `422` before the database is called.
- **Comparison limits.** At most 4 distinct options per request.
### `GET /api/trip-directory`

A read-only convenience lookup so the UI can offer trip names instead of asking
for a typed identifier. Student 3 does not own trips, which is why this is a
directory rather than `/api/trips`.

Always returns `200`. When Student 1 cannot be reached it reports
`{"available": false, "trips": []}` — distinguishable from a genuine empty list,
so a caller can fall back to free text rather than claiming there are no trips.

- **Capacity, checked on write.** A selection that would oversubscribe a service returns
  `409`. Checked when the selection is made rather than derived on every read: the party
  sizes live in Student 1's service, so one lookup on a write is cheap where a lookup per
  option per page is not. This guards demo-data integrity and is never presented to a
  traveller as a live inventory guarantee.
- **Delete is still restricted.** An option a trip still holds returns `409`. The database
  service used to refuse this itself through a foreign key; the selections live in Student 1's
  service now, so the guard is re-made here. Best-effort: if that service cannot be reached
  the delete proceeds, because blocking catalogue maintenance during someone else's outage is
  the worse failure.
- **Unusable options cannot be selected.** An option the operator has marked `sold_out` or
  `cancelled` returns `409`. Availability is declared by the operator and is not derived
  from the seat count, so this is a separate check.

`duration_minutes` stays derived in the database service, which remains the final guard for
the catalogue. Two things that used to live there have moved:

| Was | Now |
| --- | --- |
| `seats_remaining` derived in SQL from a local selections table | Derived here from Student 1's traveller totals. **`null` means unknown, not none left** — an unreachable itinerary service must not read as a full or empty service |
| `estimated_cost` stored per plan entry, overridable | Always derived from `price` and the party size, honouring `pricing_basis`. A whole-vehicle hire is not multiplied by the traveller count |

## Status codes

| Code | Meaning |
| --- | --- |
| `400 BAD_REQUEST` | Unsupported query parameter. |
| `404 NOT_FOUND` | Unknown option, trip, or selection. |
| `409 CONFLICT` | Duplicate id, capacity exceeded, or an unusable option selected. |
| `422 VALIDATION_ERROR` | Field or business-rule validation failure. |
| `422 PROMPT_BUDGET_EXCEEDED` | Too much transport context for one AI request. |
| `502 BAD_GATEWAY` | Database service, AI-Mode, or the MCP server returned something unusable. |
| `503 DEPENDENCY_UNAVAILABLE` | Database service, AI-Mode, the MCP server, or the RAG server unreachable. |
| `503 MCP_DISABLED` | MCP lookups are switched off in this environment. |
| `503 RAG_DISABLED` | The transport guide is switched off in this environment. |
| `503 INDEX_NOT_READY` | The shared RAG index has not been built. |
| `504 DEPENDENCY_TIMEOUT` | Database service or the MCP server too slow. |

## Local checks

```bash
cd student-3
python -m pip install -e .[dev]
python -m ruff check backend/student3_backend_service tests/backend
python -m pytest tests/backend
```

The backend suite runs the **real** database service in-process rather than a stub, so every
test exercises the true contract, including its validation and error envelopes.
