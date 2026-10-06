# Release 1 AI, RAG, and MCP Interaction Flow

Related documents:

- [Release 1 shared RAG architecture](./release-1-shared-rag-architecture.md)
- [Release 1 shared RAG contract](./release-1-rag-contract.md)
- [ADR 0004: Shared model-directed MCP generation](./decisions/0004-shared-mcp-generation.md)
- [Shared MCP server README](../../ai-services/mcp-server/README.md)
- [Local host services runbook](../reports/release-1/local-host-services-runbook.md)

These diagrams show the target Release 1 flow. Every MCP tool call is made by
the model through AI-Mode `/generate`. Feature backends do not call the MCP
server directly. The Student 1, 3, and 5 slices are being brought in line with
this before submission.

## 1. End-to-end flow

```mermaid
flowchart TB
    User(["User in browser"])

    subgraph Compose["Docker Compose application"]
        direction TB
        FE["Feature frontends<br/>Students 1-5<br/>Jinja + HTMX panels:<br/>AI, MCP tool data, RAG guide"]

        subgraph BE["Feature backends: public APIs"]
            direction TB
            AIRoutes["AI / assistant routes<br/>S1 POST /api/trips/{id}/ai-suggestions<br/>S2 POST /accommodation/assistant<br/>S3 POST /api/transport-options/recommendations<br/>S4 POST /activity/assistant<br/>S5 POST /api/v1/budgets/{id}/ai-analysis"]
            RagRoutes["RAG routes<br/>S1 POST /api/trips/{id}/rag-query<br/>S2 POST /accommodation/knowledge<br/>S3 POST /api/transport-options/rag-query<br/>S4 POST /activity/knowledge<br/>S5 POST /api/v1/rag/query"]
            CRUD["Ordinary CRUD and<br/>public data APIs"]
        end

        DB[("Private database services<br/>one per student")]
    end

    subgraph Host["Local host: not containerised"]
        direction TB
        AIMode["AI-Mode :8006<br/>POST /generate: MCP tool loop<br/>POST /generate-plain: no tools<br/>POST /embed"]
        Ollama["Ollama :11434<br/>chat + embedding models"]

        subgraph MCP["Shared MCP server :8012/mcp"]
            direction TB
            Registry["Tool registry<br/>names, descriptions, JSON schemas<br/>envelope: ok, data or error,<br/>correlation_id, source"]
            T1["Student 1 tools<br/>trip_get_context<br/>trips_list_itinerary_items"]
            T2["Student 2 tools<br/>accommodations_search<br/>accommodations_get<br/>accommodations_committed_costs"]
            T3["Student 3 tools<br/>transport_search<br/>transport_get<br/>transport_compare<br/>transport_trip_costs"]
            T4["Student 4 tools<br/>activities_search, activities_get<br/>activities_list_categories<br/>activities_committed_costs<br/>activities_create, activities_update,<br/>activities_delete"]
            T5["Student 5 tools<br/>budgets_list<br/>budgets_get_summary<br/>expenses_list"]
            Registry --- T1 & T2 & T3 & T4 & T5
        end

        subgraph RAG["Shared RAG server :8011"]
            direction TB
            Query["POST /query<br/>feature + query + top_k"]
            Index[("SQLite RAG index<br/>chunks, hashes, vectors")]
            Gate{"Max retrieval score<br/>above threshold?"}
            Validate["Validate citation IDs<br/>against retrieved chunks;<br/>compute confidence from scores"]
            Insufficient["Fixed insufficient-context<br/>response, no citations"]
            Grounded["Grounded answer,<br/>citations, confidence category"]
        end
    end

    User -->|"1. form or HTMX request"| FE
    FE -->|"2. own backend only"| AIRoutes & RagRoutes & CRUD
    CRUD -->|"sole caller"| DB

    %% Model-directed MCP generation
    AIRoutes -->|"3a. prompt + response schema<br/>host.docker.internal:8006"| AIMode
    AIMode -->|"list_tools on every request"| Registry
    AIMode <-->|"chat with tool definitions"| Ollama
    AIMode -->|"validated tools/call"| Registry

    %% MCP execution against public APIs
    T1 & T2 & T3 & T4 & T5 -->|"public HTTP APIs only<br/>published host ports"| CRUD

    %% RAG
    RagRoutes -->|"3b. host.docker.internal:8011"| Query
    Query -->|"embed query"| AIMode
    Query -->|"feature + shared cosine search"| Index
    Index --> Gate
    Gate -->|"no"| Insufficient
    Gate -->|"yes: /generate-plain<br/>with retrieved chunks"| AIMode
    AIMode -->|"answer + chunk IDs"| Validate
    Validate -->|"no valid citations"| Insufficient
    Validate -->|"valid"| Grounded

    %% Responses
    AIMode -.->|"final answer + tools trace"| AIRoutes
    Insufficient & Grounded -.-> RagRoutes
    AIRoutes & RagRoutes -.->|"4. partial templates"| FE
    FE -.->|"5. answer, tool data, citations,<br/>confidence, or clear failure"| User

    classDef tool fill:#FAECE7,stroke:#993C1D,color:#712B13
    classDef logic fill:#FBEAF0,stroke:#993556,color:#72243E,stroke-dasharray:5 3
    class T1,T2,T3,T4,T5 tool
    class Gate,Validate,Insufficient,Grounded logic
```

Plain boxes are modules or services. Coral boxes are MCP tools registered on
the shared MCP server, not separate services. Pink dashed boxes are logic
steps inside the RAG server, not separate modules. Solid arrows are requests.
Dotted arrows are responses. Every connection from
Compose to a host process uses the `host.docker.internal:host-gateway`
mapping, because container `localhost` is not the host.

## 2. Model-directed MCP generation sequence

```mermaid
sequenceDiagram
    actor User
    participant UI as Feature frontend
    participant API as Feature backend
    participant AI as AI-Mode :8006
    participant LLM as Ollama
    participant MCP as MCP server :8012/mcp
    participant Pub as Owning public backend API

    User->>UI: Ask assistant question
    UI->>API: POST AI or assistant route
    API->>AI: POST /generate (trusted prompt, response schema)
    AI->>MCP: initialize + tools/list (full catalogue)
    MCP-->>AI: 19 tools with names, descriptions, schemas
    loop Bounded tool rounds
        AI->>LLM: Chat with tool definitions
        LLM-->>AI: Tool call(s) or final answer
        opt Model requested a known, valid tool
            AI->>MCP: tools/call(name, arguments)
            MCP->>Pub: Fixed public HTTP route
            Pub-->>MCP: Public response
            MCP-->>AI: Envelope {ok, data | error}
        end
    end
    AI->>LLM: Schema-constrained final format (tools disabled)
    LLM-->>AI: Final JSON
    AI-->>API: Response + tools trace (actual returned data)
    API-->>UI: Presentation model with tool results
    UI-->>User: Answer plus displayed MCP tool data or failure
```

## 3. Explanation

### Frontend and backend/API interactions

Each feature frontend renders server-side Jinja templates and uses HTMX for
focused partial updates. It only calls its own backend. The backend exposes
two kinds of AI-related route next to its ordinary CRUD:

- **AI or assistant routes** send a trusted system prompt and a response schema
  to AI-Mode `/generate`. The model fetches the data it needs by calling MCP
  tools, and the UI shows the returned `tools` trace as evidence that the tools
  ran. The backend shapes the result for display. It does not call the MCP
  server itself, parse natural-language constraints, or define its own tools.
- **RAG routes** send a feature-scoped question to the shared RAG server's
  `/query` and display the answer, citations, and confidence category.

The browser never reaches AI-Mode, MCP, RAG, Ollama, or a database directly.
If any host AI service is disabled or unavailable, the AI panel reports a
clear failure. Ordinary CRUD keeps working.

### MCP tool layer

The shared MCP server is a host process that serves Streamable HTTP at
`:8012/mcp`. It owns every tool name, description, and input schema, and is
the only place tools are defined. Each tool:

1. validates its arguments against the advertised schema;
2. calls one fixed route on the owning student's **public** backend API, never
   a database service or an AI orchestration endpoint;
3. bounds the result (`limit` 1–50, 64 KiB provider body, 32 KiB tool data);
4. returns a structured envelope: `{"ok": true, "data": ...}`, or
   `{"ok": false, "error": {"code", "message", "retryable"}}` with MCP
   `isError: true`.

Callers cannot choose a URL, HTTP method, raw body, or provider route.
Provider error bodies are never forwarded.

### Registered tools

| Owner | Tools | Kind |
| --- | --- | --- |
| Student 1: trips and itinerary | `trip_get_context`, `trips_list_itinerary_items` | Read |
| Student 2: accommodation | `accommodations_search`, `accommodations_get`, `accommodations_committed_costs` | Read |
| Student 3: transport | `transport_search`, `transport_get`, `transport_compare`, `transport_trip_costs` | Read |
| Student 4: activities | `activities_search`, `activities_get`, `activities_list_categories`, `activities_committed_costs` | Read |
| Student 4: activities | `activities_create`, `activities_update`, `activities_delete` (needs `confirm: true`) | Write |
| Student 5: budgets and expenses | `budgets_list`, `budgets_get_summary`, `expenses_list` | Read |

AI-Mode discovers the full catalogue of 19 tools on every `/generate` request,
including the write tools. Trusted prompts tell the model to write only when the
user explicitly asks. This is guidance, not a hard authorisation guarantee.
Writes make exactly one provider request. An ambiguous write outcome returns
`WRITE_OUTCOME_UNKNOWN` with `retryable: false` and is never retried
automatically.

### Model-directed generation loop

AI-Mode is the only process that talks to Ollama. For `/generate` it:

1. lists the MCP tools;
2. sends the tool definitions to the model;
3. validates each requested tool call and runs only known tools with valid
   arguments, with duplicate-call protection and request deadlines;
4. feeds the real tool results back to the model;
5. makes a final schema-constrained formatting call with tools disabled.

The response includes an additive `tools` trace of the data that was actually
returned. Feature UIs display this trace, because an AI narrative alone is not
evidence that a tool ran. A failed run keeps its partial trace, and any writes
already completed are not rolled back.

### RAG retrieval and grounded responses

The RAG server indexes an allowlisted manifest of Markdown and text sources,
tagged by feature, into a local SQLite index. For each `/query` it:

1. embeds the question through AI-Mode `/embed`;
2. runs a cosine search over chunks tagged with the requested feature plus
   `shared`, bounded by `top_k` (at most 10) and 12,000 characters of context;
3. returns the fixed **insufficient-context** response if the best score is
   below the calibrated threshold, without calling the model;
4. otherwise calls AI-Mode `/generate-plain` with the retrieved chunks. This
   call has no MCP tools, so tool data can never become a RAG citation;
5. rejects any citation ID that was not among the retrieved chunks and
   resolves citation metadata (path, title, section, excerpt) from the index;
6. calculates the confidence category from retrieval scores and ignores any
   confidence the model reports. If the model cites nothing, its prose is
   discarded and the insufficient-context response is returned.

The feature backend maps the result into its own presentation model. The UI
shows the answer, the citations, and the confidence category, or the
insufficient-context message.

### Failure handling

| Layer | Failure surfaced to the UI |
| --- | --- |
| MCP tool | Envelope error code: `VALIDATION_ERROR`, `NOT_FOUND`, `PROVIDER_UNAVAILABLE`, `PROVIDER_TIMEOUT`, `INVALID_RESPONSE`, `CONFLICT`, or `WRITE_OUTCOME_UNKNOWN` |
| AI-Mode `/generate` | Explicit MCP or model failure with the partial tools trace |
| RAG `/query` | `VALIDATION_ERROR` (422), `BAD_GATEWAY` (502), `DEPENDENCY_UNAVAILABLE` or `INDEX_NOT_READY` (503), `DEPENDENCY_TIMEOUT` (504) |
| Feature backend | Translates the error into the slice's own error types, never exposing raw dependency exceptions, and leaves CRUD unaffected |
