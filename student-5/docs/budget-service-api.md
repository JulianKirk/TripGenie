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
backend confirms the budget exists, then submits a natural-language request
(plus the budget and trip IDs) and the trusted `budget_tools_v1.md` system
prompt to the shared AI-Mode `/generate` endpoint. AI-Mode discovers the MCP
tool catalogue, the model decides which tools to call, and AI-Mode returns the
executed tool calls in `tools`. The backend never calls the MCP server directly.

| Action | Request sent to the model |
| --- | --- |
| `budget-summary` | Get the spending summary for this budget. |
| `expenses` | List the 20 most recent expenses for this trip. |

```json
{
  "data": {
    "action": "budget-summary",
    "correlation_id": "student5-mcp-9b1e4c2d6a7f",
    "duration_ms": 18412,
    "run_id": "aimode_01",
    "model": "llama3.1:8b",
    "provider": "ollama",
    "answer": "The remaining budget is AUD 2375.00.",
    "tools": [
      {
        "tool": "budgets_get_summary",
        "arguments": {"budget_id": "5ad9845c-a7d1-5688-b06a-63e92bed4345"},
        "status": "success",
        "duration_ms": 412,
        "result": {"structuredContent": {"ok": true, "data": {"currency": "AUD", "remaining_budget": "2375.00"}}, "isError": false},
        "error": null
      }
    ]
  }
}
```

`tools` is the AI-Mode execution trace. `status` is `success`, `error`, or
`rejected`; failed and rejected calls are returned, not hidden. An empty
`tools` list means the model called no tool, and the UI says so rather than
treating `answer` as evidence.

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
| RAG connection refused, or AI-Mode unreachable for MCP actions | 503 | `DEPENDENCY_UNAVAILABLE` (field `rag` or `ai_mode`) |
| RAG or AI-Mode client timeout | 504 | `DEPENDENCY_TIMEOUT` |
| RAG `INDEX_NOT_READY` / `DEPENDENCY_UNAVAILABLE` | 503 | upstream code preserved |
| RAG `DEPENDENCY_TIMEOUT` | 504 | upstream code preserved |
| RAG other error, AI-Mode schema mismatch, or broken invariant | 502 | `INVALID_DEPENDENCY_RESPONSE` |

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
| `STUDENT5_BACKEND_HOST_PORT` (Compose only) | n/a | `127.0.0.1:${STUDENT5_BACKEND_HOST_PORT:-18005}:8005` |
| `STUDENT5_FRONTEND_AI_ANALYSIS_TIMEOUT_SECONDS` | `120` | `230` |
| `STUDENT5_FRONTEND_RAG_TIMEOUT_SECONDS` | `150` | `150` |
| `STUDENT5_FRONTEND_MCP_TIMEOUT_SECONDS` | `230` | `230` |

Timeouts are ordered so the outer caller always waits longer than the inner
one: frontend 230 s > backend 200 s > AI-Mode's 180 s MCP tool-loop deadline
for AI analysis, frontend 150 s > backend 130 s > RAG 120 s for RAG, and
frontend 230 s > backend 200 s > AI-Mode's 180 s tool-loop deadline for MCP actions.

Since ADR 0004, AI-Mode `/generate` discovers the shared MCP catalogue on every
request, so both MCP actions and AI analysis need the host MCP server. The
budget analysis client ignores the `tools` trace; MCP actions return it.
