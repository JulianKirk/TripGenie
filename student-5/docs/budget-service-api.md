# Student 5 Budget Service API

Public API of the Student 5 backend (`student-5-backend`, container port
`8005`). The Student 5 frontend is the browser-facing caller; the shared MCP
server reads the same API from the host through the loopback-published port.
All paths below sit under `STUDENT5_BACKEND_API_PREFIX` (`/api/v1` in Compose,
`/api` by default). The private database service (`/internal`, port `8007`) is
not part of this contract.

## Envelopes

Success: `{"data": <object or list>}`.

Failure:

```json
{"error": {"code": "VALIDATION_ERROR", "message": "One or more fields failed validation.", "details": [{"field": "total_budget", "issue": "..."}]}}
```

Money is an exact two-decimal string (for example `"1250.00"`). Currency is a
three-letter uppercase ISO 4217 code. Identifiers are UUIDs except `trip_id`,
which is Student 1's external trip reference (1-100 characters).

## Diagnostics

| Method and path | Behaviour |
| --- | --- |
| `GET /health` | Process status, database dependency, and configured integration state. Never probes RAG or MCP. |
| `GET /ready` | `200` when the database service is ready, otherwise `503`. Does not depend on AI-Mode, RAG, MCP, or provider services. |

```json
{"data": {"status": "healthy", "service": "student-5-backend", "dependencies": {"database": true}, "integrations": {"rag": "disabled", "mcp": "disabled"}}}
```

`integrations.rag` and `integrations.mcp` are `enabled` or `disabled` and
reflect configuration only (Release 1).

## Budgets and expenses (Release 0)

| Method and path | Purpose |
| --- | --- |
| `GET /trips` | Trip directory proxied from the Student 1 trips API. |
| `GET /budgets?trip_id=` | List budgets, optionally for one trip. |
| `POST /budgets` | Create a budget (`201`). One budget per trip; a duplicate returns `409 CONFLICT`. |
| `GET /budgets/{budget_id}` | Read one budget. |
| `PATCH /budgets/{budget_id}` | Partially update a budget. |
| `DELETE /budgets/{budget_id}` | Delete a budget; expenses are kept. |
| `GET /budgets/{budget_id}/summary` | Deterministic summary with provider availability. |
| `POST /budgets/{budget_id}/ai-analysis` | Advisory AI analysis through AI-Mode. Body: `{"question": "1-500 chars"}`. |
| `GET /expenses?trip_id=&category=&date_from=&date_to=` | List and filter expenses. |
| `POST /expenses` | Create an expense (`201`). |
| `GET /expenses/{expense_id}` | Read one expense. |
| `PATCH /expenses/{expense_id}` | Partially update an expense. |
| `DELETE /expenses/{expense_id}` | Delete an expense. |

Budget fields: `trip_id`, `currency`, `total_budget`, `accommodation_budget`,
`transport_budget`, `activities_budget`, `food_budget`, `other_budget`
(allocations default to `"0.00"` and must not exceed the total).

Expense fields: `trip_id`, `category` (`accommodation`, `transport`,
`activities`, `food`, `shopping`, `other`), `description`, `amount` (> 0),
`currency`, `date`, optional `payment_method` and `notes`.

Summary fields: `budget_id`, `trip_id`, `currency`, `total_budget`,
`actual_spending`, `actual_spending_complete`, `unconverted_expense_count`,
`committed_costs`, `committed_costs_complete`, `remaining_budget`,
`remaining_budget_complete`, `category_totals`, and `providers`
(`transport`, `accommodation`, `activities`, each with `status`
`available` / `unavailable` / `invalid_response`, `subtotal`, `currency`,
`detail`, `items`). See [budget-rules.md](./budget-rules.md) for the
calculation rules.

## Grounded budget knowledge (Release 1)

### `POST /rag/query`

Request: `{"question": "How is the remaining budget calculated?"}` (1-500
characters after trimming; unknown fields are rejected).

The backend sends the shared RAG server `POST /query` with a fixed
`feature: "student-5"`, `top_k: 5`, and a `student5-rag-<12 hex>` correlation
ID. The browser cannot choose the feature, `top_k`, URL, or model. The response
is validated against RAG `schema_version: "1"`, including the rule that an
insufficient-context answer has no citations and a grounded answer has at least
one.

```json
{
  "data": {
    "answer": "Remaining budget is the total budget minus committed costs and actual spending.",
    "confidence_category": "high",
    "insufficient_context": false,
    "citations": [
      {
        "source_id": "student-5-budget-rules",
        "title": "Student 5 Budget and Expense Rules",
        "section": "Remaining budget",
        "path": "student-5/docs/budget-rules.md",
        "chunk_id": "student-5-budget-rules:7:ab12cd",
        "excerpt": "remaining_budget = total_budget - actual_spending - committed_costs"
      }
    ],
    "retrieval": {"requested_top_k": 5, "returned_chunks": 3, "maximum_score": 0.81},
    "run_id": "rag_01",
    "correlation_id": "student5-rag-3f9c2a1b7d4e"
  }
}
```

`confidence_category` is `high`, `medium`, `low`, or `insufficient_context`,
calculated by the RAG server from retrieval scores and passed through
unchanged.

## Shared MCP tools (Release 1)

### `POST /budgets/{budget_id}/mcp/{action}`

No request body. `action` must be one of the allowlisted keys below. The
backend confirms the budget exists before calling MCP, builds the tool
arguments server-side, and calls the shared MCP server's `tools/call` over MCP
Streamable HTTP (JSON-RPC 2.0, stateless, JSON responses).

| Action | MCP tool | Arguments |
| --- | --- | --- |
| `budget-summary` | `budgets_get_summary` | `{"budget_id": <path budget>}` |
| `expenses` | `expenses_list` | `{"trip_id": <budget trip>, "limit": 20}` |

```json
{
  "data": {
    "action": "budget-summary",
    "tool": "budgets_get_summary",
    "correlation_id": "student5-mcp-9b1e4c2d6a7f",
    "duration_ms": 412,
    "result": {"budget_id": "5ad9845c-a7d1-5688-b06a-63e92bed4345", "currency": "AUD", "remaining_budget": "2375.00"}
  }
}
```

`result` is the tool's `data` object (the full summary for `budget-summary`;
`expenses`, `count`, and `truncated` for `expenses`). Results over 32 KB are
rejected.

### Student 5 tools on the shared MCP server

Implemented in `ai-services/mcp-server/tripgenie_mcp/tools.py`. All are
read-only GET calls to this API.

| Tool | Inputs | Output and boundary |
| --- | --- | --- |
| `budgets_list` | `trip_id?` (1-100), `limit?` (1-50, default 20) | `budgets[]` (`budget_id`, `trip_id`, `currency`, `total_budget`), `count`, `truncated`. |
| `budgets_get_summary` | `budget_id` (UUID) | The summary above; `unavailable` providers are never turned into zero. |
| `expenses_list` | `trip_id` (1-100), `category?`, `date_from?`, `date_to?` (ISO), `limit?` | `expenses[]` without `notes` or `payment_method`, `count`, `truncated`. |

## Release 1 error codes

| Situation | HTTP | Code |
| --- | ---: | --- |
| RAG or MCP disabled by configuration (no outbound call) | 503 | `RAG_DISABLED` / `MCP_DISABLED` |
| Empty or over-long question; unknown MCP action; malformed UUID | 422 | `VALIDATION_ERROR` |
| Budget not found (before any MCP call) | 404 | `NOT_FOUND` |
| RAG or MCP connection refused | 503 | `DEPENDENCY_UNAVAILABLE` (field `rag` or `mcp`) |
| RAG or MCP client timeout | 504 | `DEPENDENCY_TIMEOUT` |
| RAG `INDEX_NOT_READY` / `DEPENDENCY_UNAVAILABLE` | 503 | upstream code preserved |
| RAG `DEPENDENCY_TIMEOUT` | 504 | upstream code preserved |
| RAG other error, schema mismatch, or broken invariant | 502 | `INVALID_DEPENDENCY_RESPONSE` |
| MCP tool not registered | 503 | `DEPENDENCY_UNAVAILABLE` (issue `tool not registered`) |
| MCP tool returned a structured error | 502 | `MCP_TOOL_ERROR` (tool error code in `details[0].issue`) |
| MCP result malformed or over 32 KB | 502 | `INVALID_DEPENDENCY_RESPONSE` |

Logs for RAG and MCP calls contain only the correlation ID, action, outcome, and
duration; never the question, answer, excerpts, or tool payloads.

## Configuration

| Variable | Default | Compose |
| --- | --- | --- |
| `STUDENT5_BACKEND_AI_MODE_BASE_URL` | `http://ai-mode:8006` | `http://host.docker.internal:8006` (host AI-Mode, ADR 0004) |
| `STUDENT5_BACKEND_AI_MODE_TIMEOUT_SECONDS` | `20` | `200` |
| `STUDENT5_BACKEND_RAG_ENABLED` | `false` | `${STUDENT5_BACKEND_RAG_ENABLED:-true}` |
| `STUDENT5_BACKEND_RAG_BASE_URL` | `http://host.docker.internal:8011` | same |
| `STUDENT5_BACKEND_RAG_TIMEOUT_SECONDS` | `130` (connect 3) | `130` |
| `STUDENT5_BACKEND_MCP_ENABLED` | `false` | `${STUDENT5_BACKEND_MCP_ENABLED:-true}` |
| `STUDENT5_BACKEND_MCP_BASE_URL` | `http://host.docker.internal:8012/mcp` | same |
| `STUDENT5_BACKEND_MCP_TIMEOUT_SECONDS` | `40` (connect 3) | `40` |
| `STUDENT5_BACKEND_HOST_PORT` (Compose only) | n/a | `127.0.0.1:${STUDENT5_BACKEND_HOST_PORT:-18005}:8005` |
| `STUDENT5_FRONTEND_AI_ANALYSIS_TIMEOUT_SECONDS` | `120` | `230` |
| `STUDENT5_FRONTEND_RAG_TIMEOUT_SECONDS` | `150` | `150` |
| `STUDENT5_FRONTEND_MCP_TIMEOUT_SECONDS` | `60` | `60` |

Timeouts are ordered so the outer caller always waits longer than the inner
one: frontend 230 s > backend 200 s > AI-Mode's 180 s MCP tool-loop deadline
for AI analysis, frontend 150 s > backend 130 s > RAG 120 s for RAG, and
frontend 60 s > backend 40 s > MCP provider calls (30 s) for MCP.

Since ADR 0004, AI-Mode `/generate` discovers the shared MCP catalogue on every
request, so AI analysis also needs the host MCP server. Its additive `tools`
trace is ignored by the budget analysis client.
