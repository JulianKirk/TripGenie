# TripGenie shared AI-Mode service

This service provides the shared runtime boundary between TripGenie services
and a host-managed Ollama runtime.

- Runtime: FastAPI on Python 3.11
- Provider client: the existing pinned `ollama==0.6.2` SDK.
- Scope: bounded model-directed MCP generation and embeddings
- Out of scope: streaming, retained chat sessions, retrieval/indexing,
  and multi-agent orchestration

Student backends supply prompts and final-answer schemas. This service owns MCP
discovery and the tool loop; MCP owns tool descriptions and input schemas. All
advertised tools, including writes, are available to every generation caller.
Clients must not automatically retry a run that has executed tools.

## Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `AI_MODE_SERVICE_NAME` | `ai-mode` | Service name reported by health endpoints. |
| `AI_MODE_OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Host Ollama base URL used only by this shared service. Container deployments must override this to `http://host.docker.internal:11434`. |
| `AI_MODE_DEFAULT_MODEL` | `qwen2.5:0.5b` | Default approved model used when callers do not request an override. |
| `AI_MODE_ALLOWED_MODELS` | `qwen2.5:0.5b,llama3.1:8b` | Allowlist of approved runtime models. Arbitrary provider model names are rejected. |
| `AI_MODE_DEFAULT_EMBEDDING_MODEL` | `nomic-embed-text` | Default approved embedding model. |
| `AI_MODE_ALLOWED_EMBEDDING_MODELS` | `nomic-embed-text` | Separate allowlist for embedding models. |
| `AI_MODE_TIMEOUT_SECONDS` | `15` | Timeout for Ollama list, generate, and embed calls. |
| `AI_MODE_MAX_PROMPT_CHARS` | `12000` | Max combined `prompt` + optional `system` length. Student backends should pre-budget prompts to this same contract. |
| `AI_MODE_MAX_SCHEMA_CHARS` | `8000` | Max accepted JSON-schema serialized length. |
| `AI_MODE_MAX_RESPONSE_BYTES` | `16384` | Max accepted provider response size. |
| `AI_MODE_MAX_EMBED_INPUTS` | `32` | Maximum texts accepted by one embedding request. |
| `AI_MODE_MAX_EMBED_INPUT_CHARS` | `12000` | Maximum characters in each embedding input. |
| `AI_MODE_CONTEXT_TOKENS` | `32768` | Native chat context window for the full tool catalogue and conversation. |
| `AI_MODE_MCP_URL` | `http://127.0.0.1:8012/mcp` | Host-run shared MCP endpoint. |
| `AI_MODE_MCP_TIMEOUT_SECONDS` | `15` | MCP request timeout. |
| `AI_MODE_AGENT_TIMEOUT_SECONDS` | `180` | Whole generation-run deadline. |
| `AI_MODE_AGENT_MAX_TURNS` | `8` | Maximum tool-decision rounds, plus final schema formatting. |
| `AI_MODE_AGENT_MAX_CALLS` | `16` | Maximum executed tool calls per run. |
| `AI_MODE_AGENT_CONTEXT_CHARS` | `120000` | Bounded serialized conversation and full tool catalogue. |
| `AI_MODE_AGENT_RESULT_BYTES` | `32768` | Maximum serialized result per tool call. |
| `AI_MODE_MAX_EMBED_DIMENSIONS` | `4096` | Maximum accepted provider vector dimension. |

## Host Ollama prerequisite

TripGenie assumes Ollama is installed and managed on the **host machine**, not
inside Docker.

1. Install Ollama on the host OS using the official installer/package for that platform.
2. Start Ollama so the shared AI-Mode service can reach its HTTP API.
   - Native `ai-mode` runs use the default `AI_MODE_OLLAMA_BASE_URL=http://127.0.0.1:11434`.
   - Compose backends call containerised AI-Mode at `http://ai-mode:8006`; AI-Mode reaches host Ollama through `http://host.docker.internal:11434`.
3. Pull the approved chat and embedding models on the host:

   ```bash
   ollama pull qwen2.5:0.5b
   ollama pull nomic-embed-text
   ```

4. Verify the host runtime before exercising the shared service:

   ```bash
   curl http://127.0.0.1:11434/api/tags
   ```

Platform notes:

- Windows/macOS native runs can use the loopback default above.
- On native Linux, Ollama and MCP must listen on a Docker-accessible host interface. See [host setup](../../student-4/docs/mcp-assistant.md).
- Tests and CI in this repository use mocked provider transports only. They do **not** install, start, or download Ollama/models.

## Public API

### `GET /health`

- Returns `200`
- Reports overall service status plus Ollama dependency status
- `status=degraded` when Ollama is unavailable, invalid, or missing either
  configured default model

Example:

```json
{
  "data": {
    "status": "ok",
    "service": "ai-mode",
    "dependencies": {
      "ollama": {
        "status": "ok",
        "service": "ollama",
        "detail": "Ollama responded successfully and the configured models are available.",
        "code": null
      }
    }
  }
}
```

### `GET /ready`

- Returns `200` when the configured/default chat and embedding models are
  available
- Returns `503` when the provider is unavailable or either model is missing

### `POST /generate`

Each request starts a fresh non-streaming native Ollama chat/tool conversation.
The service discovers the full configured MCP catalogue (including pagination),
sends its descriptions and argument schemas to the model, executes model-selected
calls and returns their results until the model answers. No domain-specific prompt
parsing, recommendation filtering or answer rewriting happens here.

When `schema` is provided, a final model formatting call with tools disabled emits
that schema. `response` remains a string; `done`, `model`, `provider`, `run_id` and
`correlation_id` retain their existing meanings. Success responses also contain
`tools`: ordered entries with `tool`, `arguments`, `status`, `duration_ms`, `error`
and `result` (the actual MCP result). Errors after execution add a top-level `tools`
trace beside the existing `error` envelope. A failed run does not undo completed
writes. Oversized results are omitted but their known execution status is retained.

All tools are executable; prompts should direct writes only for explicit requests.
This is a trusted local service, not a new authorization layer. Unknown tool names,
invalid arguments, external schema references, duplicate non-read-only calls and
excessive execution are rejected. Protocol validation does not interpret user intent.
MCP must be running for generation, even if no tool is ultimately called. A tool's
provider may be unavailable independently and returns an explicit tool error.
`/embed` does not connect to MCP. Existing health/readiness report the Ollama model
baseline; `/generate` reports MCP availability at request time.

Use a generation model that supports native tool calls. Allow enough consumer HTTP
time for several inference rounds (Student 4 defaults to 210 seconds).
The complete MCP schemas are sent on every tool-capable round. Health checks and
embeddings retain the existing SDK methods. Native chat uses the pinned SDK's
lower-level `_request` helper because its high-level `chat()` tool serializer drops
nested JSON Schema keywords. This narrow compatibility workaround retains SDK
transport, authentication, error handling and response validation. Outgoing-payload
tests protect schema preservation; review this helper when upgrading the SDK.
The model's Ollama chat template must also retain tool definitions after a tool
response. The installed `llama3.1:8b` template exposes definitions only on the last
user turn, so use a template that retains them, such as `qwen2.5:7b`, for multi-step
tool workflows. Set both `AI_MODE_DEFAULT_MODEL` and `AI_MODE_ALLOWED_MODELS` when
selecting a model outside the default allowlist.

An optional `system` string carries trusted application instructions separately from
`prompt` (user request and other untrusted context). AI-Mode forwards it as a system-role message in the
provider chat conversation. Existing callers
can omit it. A supplied string must be nonblank; `null` behaves like omission. The
combined character count of both fields must fit `AI_MODE_MAX_PROMPT_CHARS`; splitting
input does not increase the allowance. Role separation improves instruction clarity,
but application authorization and output validation remain mandatory. Never put raw
user input or tool observations into `system`.

`correlation_id` must be a safe single-line value that starts with a letter or digit, uses only letters, digits, `.`, `_`, `:`, or `-`, and stays within 64 characters.

Request:

```json
{
  "prompt": "Return JSON only for this trip-planning request.",
  "model": "qwen2.5:0.5b",
  "schema": {
    "type": "object",
    "properties": {
      "suggestions": {
        "type": "array"
      }
    },
    "required": ["suggestions"]
  },
  "correlation_id": "trip_ai_20270402",
  "metadata": {
    "feature": "student-1-trip-suggestions",
    "trip_id": "trip_2027_sydney_getaway",
    "attempt": "1"
  }
}
```

Response:

```json
{
  "data": {
    "run_id": "aimode_1234abcd5678",
    "correlation_id": "trip_ai_20270402",
    "model": "qwen2.5:0.5b",
    "provider": "ollama",
    "response": "{\"suggestions\":[]}",
    "done": true
  }
}
```

The shared response envelope keeps the approved requested model authoritative. If provider success metadata reports a blank, invalid, or unexpected model name, that provider field is not passed through to consumers.

### `POST /embed`

Creates bounded embeddings for the shared RAG service. Chat and embedding
model allowlists are independent.

Request:

```json
{
  "inputs": [
    "First bounded source chunk",
    "Second bounded source chunk"
  ],
  "model": "nomic-embed-text",
  "correlation_id": "rag-ingest-01",
  "metadata": {
    "feature": "shared-rag"
  }
}
```

Response:

```json
{
  "data": {
    "run_id": "aimode_1234abcd5678",
    "correlation_id": "rag-ingest-01",
    "model": "nomic-embed-text",
    "provider": "ollama",
    "dimension": 768,
    "embeddings": [[0.1, 0.2], [0.3, 0.4]]
  }
}
```

AI-Mode rejects mismatched vector counts, inconsistent or excessive
dimensions, non-finite values, unavailable models, provider timeouts, and
malformed responses.

## Stable errors

The service normalizes provider failures into bounded envelopes.

### Validation error

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "One or more fields failed validation.",
    "details": [
      {
        "field": "model",
        "issue": "must be one of: qwen2.5:0.5b, llama3.1:8b"
      }
    ]
  }
}
```

### Provider unavailable or timeout

```json
{
  "error": {
    "code": "DEPENDENCY_UNAVAILABLE",
    "message": "The AI provider is unavailable.",
    "details": [
      {
        "field": "ai_mode",
        "issue": "provider connection failed"
      }
    ]
  }
}
```

```json
{
  "error": {
    "code": "DEPENDENCY_TIMEOUT",
    "message": "The AI provider did not respond before the configured timeout.",
    "details": [
      {
        "field": "ai_mode",
        "issue": "provider request timed out"
      }
    ]
  }
}
```

### Model unavailable

```json
{
  "error": {
    "code": "MODEL_UNAVAILABLE",
    "message": "Requested AI model is not available.",
    "details": [
      {
        "field": "model",
        "issue": "model 'llama3.1:8b' is not available in Ollama"
      }
    ]
  }
}
```

Generic provider `404` responses that do **not** explicitly describe a missing model are treated as provider/base-path failures, not as `MODEL_UNAVAILABLE`.

### Malformed or oversized provider response

```json
{
  "error": {
    "code": "BAD_GATEWAY",
    "message": "The AI provider returned a malformed generate response.",
    "details": [
      {
        "field": "ai_mode",
        "issue": "provider response body was malformed"
      }
    ]
  }
}
```

```json
{
  "error": {
    "code": "DEPENDENCY_RESPONSE_TOO_LARGE",
    "message": "The AI provider returned a response that exceeded the configured size limit.",
    "details": [
      {
        "field": "ai_mode",
        "issue": "provider response exceeded 16384 bytes"
      }
    ]
  }
}
```

## Consumer guidance for Students 2-5

Student backends call the shared generation agent over the existing HTTP contract.
They can consume the additive tool trace or ignore it for tool-free responses.
No MCP SDK or duplicated tool catalogue is needed in a feature backend.

### Recommended environment-variable pattern

| Consumer | Base URL variable | Timeout variable |
| --- | --- | --- |
| Student 1 | `STUDENT1_BACKEND_AI_MODE_BASE_URL` | `STUDENT1_BACKEND_AI_MODE_TIMEOUT_SECONDS` |
| Student 2 | `STUDENT2_BACKEND_AI_MODE_BASE_URL` | `STUDENT2_BACKEND_AI_MODE_TIMEOUT_SECONDS` |
| Student 3 | `STUDENT3_BACKEND_AI_MODE_BASE_URL` | `STUDENT3_BACKEND_AI_MODE_TIMEOUT_SECONDS` |
| Student 4 | `STUDENT4_BACKEND_AI_MODE_BASE_URL` | `STUDENT4_BACKEND_AI_MODE_TIMEOUT_SECONDS` |
| Student 5 | `STUDENT5_BACKEND_AI_MODE_BASE_URL` | `STUDENT5_BACKEND_AI_MODE_TIMEOUT_SECONDS` |

### Backend responsibilities that remain outside this service

- render the full prompt for the relevant domain feature
- define any domain output schema
- validate generated content against business rules
- retry correctable domain failures only when the previous run executed no tools
- enforce `persisted=false` / `approval_required=true` or equivalent approval rules

### Minimal consumer example

See [`examples/python_httpx_consumer.py`](./examples/python_httpx_consumer.py) for an async `httpx` pattern.

## Logging and privacy

The service logs safe metadata only:

- stage
- run ID
- correlation ID
- model
- prompt/schema lengths
- metadata count
- error code

It must not log full prompts, raw user context, or raw provider output.
Correlation IDs and other logged fields are sanitized defensively to stay single-line.

## Runtime expectation

AI-Mode runs in Docker Compose. MCP, RAG, Ollama, and the validation loop remain
host processes. Start the gateway with:

```bash
docker compose --env-file shared/configuration/.env.example up --build -d ai-mode
```

- Backend-to-AI-Mode URL: `http://ai-mode:8006`.
- Host RAG/local clients: `http://127.0.0.1:8006` (loopback-only published port).
- AI-Mode-to-Ollama: `http://host.docker.internal:11434`.
- AI-Mode-to-MCP: `http://host.docker.internal:8012/mcp`.
- AI-Mode has the Linux `host.docker.internal:host-gateway` mapping. Host MCP
  and Ollama must listen on that reachable interface, not only host loopback.
  See the [host-binding guide](../../student-4/docs/mcp-assistant.md).

Ollama remains a host prerequisite; Compose and CI do not install, start, or download Ollama or its models.

### Instruction formatting

System instructions and user input use separate chat roles. MCP responses use tool
messages. Native tool calls run without a final-output JSON grammar; if a caller
supplies `schema`, final formatting uses that grammar after tool work finishes.
Tool descriptions are passed directly from MCP. Improve prompts/descriptions for
model-quality issues rather than implementing domain-specific reasoning in Python.
