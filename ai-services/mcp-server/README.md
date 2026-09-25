# Shared MCP server (Release 1)

One read-only, host-run MCP server for TripGenie's five public student backends.
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

The server binds to loopback only. Docker Desktop backends reach it at
`http://host.docker.internal:8012/mcp` when configured by their owners. Never
bind it to a public interface without adding authentication. Host-side backend
ports must be published on loopback first (Compose host-connectivity issue
#129); this server does not change Compose or other students' services.

| Environment variable | Default public backend URL |
| --- | --- |
| `MCP_STUDENT_1_URL` | `http://127.0.0.1:18001` |
| `MCP_STUDENT_2_URL` | `http://127.0.0.1:9000` |
| `MCP_STUDENT_3_URL` | `http://127.0.0.1:18003` |
| `MCP_STUDENT_4_URL` | `http://127.0.0.1:18008` |
| `MCP_STUDENT_5_URL` | `http://127.0.0.1:18005` |

`MCP_HOST` (default `127.0.0.1`) and `MCP_PORT` (default `8012`) set the
server binding. Set each URL to the **public backend root**, without an API
prefix. The defaults follow the proposed loopback scheme; Student 2 already
publishes port 9000. If #129 chooses other ports, override the relevant URLs.
The Student 5 backend serves `/api/v1` in Compose; Student 1 and 3 serve `/api`.

## Tool contract

All tools are reads. IDs come only from provider responses; callers discover
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
| Student 4 | `activities_search` | `text?`, `limit?` | Activity `items`, `count`, `truncated`; exact AUD `price`, `pricing_basis` (`PER_PERSON`/`FLAT_ADMISSION`) and unknown nullable facts preserved. |
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
`PROVIDER_TIMEOUT`, and `INVALID_RESPONSE`. Missing or unregistered tool names
are rejected by MCP itself. Provider error bodies are never forwarded. No tool
performs a write or holds a Student 1 transaction. Avoid calling the Student 5
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
be running and their loopback host ports to be published by #129.