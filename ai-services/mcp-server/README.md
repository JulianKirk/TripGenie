# Shared MCP server (Release 1)

One host-run MCP server for TripGenie's five public student backends.
The server never reads a database or calls Ollama, and is not a Compose service.
It uses the pinned Python MCP SDK `1.26.0` with Streamable HTTP at `/mcp`.

## Start and inspect

From `ai-services/mcp-server/` with Python 3.11:

```powershell
python -m pip install -e ".[dev]"
python -m tripgenie_mcp serve
```

In a second terminal:

```powershell
python -m tripgenie_mcp inspect
python -m tripgenie_mcp call trip_get_context '{"trip_id":"trip_2026_sydney"}'
python -m tripgenie_mcp call accommodations_search '{"limit":5}'
python -m tripgenie_mcp call transport_search '{"limit":5}'
python -m tripgenie_mcp call activities_list_categories
python -m tripgenie_mcp call budgets_list '{"limit":5}'
```

`GET http://127.0.0.1:8012/health` reports process liveness; `/ready` reports
that the tool server is serving. Both are diagnostic only and do **not** probe
downstream services (Student 2 has no `/ready`). A disconnected provider returns
a structured error when its tool is called. The `call` command prints the MCP
`structuredContent` alongside protocol metadata.

The server binds to loopback by default. Docker Desktop backends reach it at
`http://host.docker.internal:8012/mcp` when configured by their owners. Never
bind it to a public interface without adding authentication. Host-side backend
ports must be reachable from the host. Compose now publishes Student 1 at
127.0.0.1:18001 and Student 4 at 127.0.0.1:18008. On native Linux, see
[the host-binding guide](../../student-4/docs/mcp-assistant.md) for restricted
Docker-bridge binding and CLI `--url`; loopback-only listeners cannot be
reached through the container host gateway.

| Environment variable | Default public backend URL |
| --- | --- |
| `MCP_STUDENT_1_URL` | `http://127.0.0.1:18001` |
| `MCP_STUDENT_2_URL` | `http://127.0.0.1:9000` |
| `MCP_STUDENT_3_URL` | `http://127.0.0.1:18003` |
| `MCP_STUDENT_4_URL` | `http://127.0.0.1:18008` |
| `MCP_STUDENT_5_URL` | `http://127.0.0.1:18005` |

`MCP_HOST` (default `127.0.0.1`) and `MCP_PORT` (default `8012`) set the
server binding. Set each URL to the **public backend root**, without an API
prefix. Student 1 and 4 defaults match Compose loopback ports; Student 2
publishes port 9000. Other provider ports must be published by their owners;
override the relevant URLs if they use different bindings.
The Student 5 backend serves `/api/v1` in Compose; Student 1 and 3 serve `/api`.

## Tool contract

Activity catalogue CRUD is available to trusted external local clients; other
tools are reads. IDs come only from provider responses; callers discover
IDs using search/list tools. `limit` defaults to 20, accepts 1-50, and caps
returned rows; provider list bodies are capped at 64 KiB and tool data at
32 KiB. Empty lists are successful. Read-only Student 2 and 4 `QUERY` filters
are used internally, never exposed as arbitrary HTTP requests. The caller
cannot select a URL, method, raw body, or provider API route.

| Owner | Tool | Inputs | Output and boundary |
| --- | --- | --- | --- |
| Student 1 | `trip_get_context` | `trip_id` | Public trip detail; read only. |
| Student 1 | `trips_list_itinerary_items` | `trip_id`, `limit?` | `items`, `count`, `truncated` from the trip's itinerary. |
| Student 2 | `accommodations_search` | `country?`, `city?`, `limit?` | Accommodation `items`, `count`, `truncated`; city requires country. IDs are provider UUIDs and `price_per_night` is a two-decimal AUD string (per night). |
| Student 2 | `accommodations_get` | `accommodation_id` UUID | Public detail, including per-night price. |
| Student 2 | `accommodations_committed_costs` | `trip_id` | Public committed total, currency, and items; unknown costs are errors, not zero. |
| Student 3 | `transport_search` | `origin?`, `destination?`, `limit?` | Transport `items`, `count`, `truncated`; price is two-decimal text and `pricing_basis` is preserved. `seats_remaining: null` is unknown. |
| Student 3 | `transport_get` | `transport_id` (`transport_*`) | Public detail with pricing basis and nullable seats. |
| Student 3 | `transport_compare` | `ids` (1-4 unique `transport_*` IDs) | Compared items; response IDs must match the requested set. |
| Student 3 | `transport_trip_costs` | `trip_id` | Public trip summary with exact-string total, planned costs and option prices; pricing basis and nullable seats are preserved. |
| Student 4 | `activities_search` | `text?`, `limit?`, `offset?`, `filters?` | Activity `items`, `count`, `truncated`; exact AUD `price`, `pricing_basis` (`PER_PERSON`/`FLAT_ADMISSION`) and unknown nullable facts preserved. |
| Student 4 | `activities_create` | `activity` typed ActivityWrite | POST /activity; full created representation, status 201. |
| Student 4 | `activities_update` | `activity_id` UUID, `activity` typed ActivityWrite | PUT /activity/{id}; replaces all fields, categories and schedules, status 200. |
| Student 4 | `activities_delete` | `activity_id` UUID, `confirm: true` | DELETE /activity/{id}; hard delete acknowledgement with matching ID, status 200. |
| Student 4 | `activities_get` | `activity_id` UUID | Public detail, including exact price and pricing basis. |
| Student 4 | `activities_list_categories` | none | Public category codes and labels. |
| Student 4 | `activities_committed_costs` | `trip_id` | Public committed total, currency, and items. |
| Student 5 | `budgets_list` | `trip_id?` (1-100 chars), `limit?` | `budgets`, `count`, `truncated`; budget ID, trip ID, currency and exact total only. |
| Student 5 | `budgets_get_summary` | `budget_id` UUID | Public summary, including exact totals, `*_complete` flags, unconverted count, and `available`/`unavailable`/`invalid_response` provider states. Never turns unavailable into zero. |
| Student 5 | `expenses_list` | `trip_id` (1-100 chars), `category?`, `date_from?`, `date_to?`, `limit?` | `expenses`, `count`, `truncated`; omits notes and payment method. ISO dates and category are validated before HTTP. |

Each tool returns a structured envelope:

```json
{"ok":true,"data":{"items":[],"count":0,"truncated":false},"correlation_id":"mcp-0123456789ab","source":"student-1"}
```

Failures use `{"ok":false,"error":{"code":"PROVIDER_UNAVAILABLE","message":"Provider unreachable","retryable":true},"correlation_id":"mcp-...","source":"student-1"}` with MCP `isError: true`.
Codes are `VALIDATION_ERROR`, `NOT_FOUND`, `PROVIDER_UNAVAILABLE`,
`PROVIDER_TIMEOUT`, `INVALID_RESPONSE`, `CONFLICT`, and `WRITE_OUTCOME_UNKNOWN`. Missing or unregistered tool names
are rejected by MCP itself. Provider error bodies are never forwarded. No tool
holds a Student 1 transaction. Avoid calling the Student 5
fan-out summary inside a Student 1 write transaction.

## Checks

```powershell
python -m compileall tripgenie_mcp tests
python -m ruff check tripgenie_mcp tests
python -m ruff format --check tripgenie_mcp tests
python -m pytest -q
```

Tests use injected `httpx.MockTransport`; no live backends or host model are
needed. A live invocation of each domain requires the five public backends to
be running and their configured host ports to be reachable.

## Activity advanced search and writes

Create/update requests must fit the 32 KiB result budget including generated
record and schedule IDs. Oversized writes are rejected before provider execution.
An oversized or malformed acknowledgement after a write requires catalogue
inspection before retrying, since the mutation may already have completed.

`activities_search` remains compatible with existing `text` and `limit` calls.
It uses the public catalogue's text semantics: literal case-insensitive substrings,
with conservative single-word variants `kayaks`/`kayaking` -> `kayak` and
`walks`/`walking` -> `walk`. Multi-word phrases remain literal. This applies equally
to external MCP clients and ordinary public API callers. Assistant-specific party
budget and selected-trip eligibility checks live in the requesting backend; MCP's
price filters continue to compare listed prices.
`offset` defaults to zero; `filters` contains the public ActivityQuery fields
except `text`, `limit` and `offset`: location, categories, price, duration_minutes,
party_size, youngest_age, oldest_age, booking_required, accessibility,
availability, sort and include_inactive. The MCP limit remains 1–50. For example:

```json
{"text":"museum","limit":5,"offset":0,"filters":{"price":{"max":"25.00"},"accessibility":{"wheelchair_accessible":true}}}
```

The nested input schemas advertised by `tools/list` reject unknown fields and
validate category enums, ranges, local schedule times, recurrence, age and party
bounds. Full write schemas mirror the public
[Student 4 contract](../../student-4/docs/backend-service-api.md).
Money is canonical two-decimal text; nullable accessibility and participant
facts retain their unknown meaning. Update is a full replacement, not a patch.
Read tools advertise `readOnlyHint`; update and delete advertise destructive
behavior. These annotations describe behavior and are not access controls.

There is no MCP authentication or per-client authorization in this local server.
Loopback and DNS-rebinding checks are the existing trusted-client boundary;
any client able to reach it can call the catalogue write tools. Do not expose it
on a network without adding authentication and authorization. The Student 4
frontend agent must enforce its own read-only allowlist before every execution,
regardless of the write tools advertised here. No tool changes itinerary choices.

Writes make exactly one provider request. A timeout, transport failure, 5xx,
unexpected status or malformed acknowledgement returns `WRITE_OUTCOME_UNKNOWN`
with `retryable: false`; a write may already have happened. Inspect the catalogue
before deciding to retry. Known 404/422/409 rejections are reported separately.
A valid incoming HTTP `X-Request-ID` (1–80 letters, digits, `_` or `-`) is reused
in the tool envelope and downstream header. Otherwise the server generates one.

Protocol tests exercise initialization, tools/list and tools/call through the
Streamable HTTP ASGI endpoint with an injected provider transport; these are
not evidence of a running local catalogue or a browser workflow.
