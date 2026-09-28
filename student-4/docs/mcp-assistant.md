# Activity assistant and shared MCP integration

Each question is a separate request. The frontend calls its backend; the backend
uses AI-Mode to choose from allowed MCP tools and compose text/activity references.
MCP tools call public APIs. The backend resolves the references through MCP and
returns authoritative cards plus an execution trace. Only the user can add an
activity to a trip using the existing button. No conversation history is retained. Tool schemas are included in the model context.
Repeated successful calls move the request to a final-answer step, and the last
step is always reserved for a final answer. Its schema permits only activity IDs
already discovered in this request (or text only when none are known).

The shared MCP server supports external-client activity create/read/update/delete.
The frontend agent cannot execute those writes: the backend hides their schemas
and rejects their names even if a model requests one. See the
[shared MCP tool contract](../../ai-services/mcp-server/README.md).

## Local setup

Use Python 3.11 and install from the repository root:

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -e './student-4[dev]' -e './ai-services/mcp-server[dev]' -e './ai-services/ai-mode[dev]'
```

Ollama runs on the host. Install `llama3.1:8b` for generation and
`nomic-embed-text` for the gateway's default embedding readiness check,
then configure AI-Mode with `AI_MODE_DEFAULT_MODEL=llama3.1:8b` and an allowlist
containing that model. Do not assume the example environment file is loaded.
AI-Mode's default prompt/schema limits are sufficient for the six allowed tools.

On Docker Desktop, start host services in separate terminals:

```bash
AI_MODE_TIMEOUT_SECONDS=90 AI_MODE_DEFAULT_MODEL=llama3.1:8b .venv/bin/uvicorn ai_mode_service.app:app --host 127.0.0.1 --port 8006
.venv/bin/python -m tripgenie_mcp serve
```

On native Linux, container `host.docker.internal` maps to the Docker host gateway,
not host loopback. Bind AI-Mode and MCP to the Docker bridge address instead of
127.0.0.1, and restrict access to the local Docker network. Obtain that address:

```bash
docker network inspect bridge --format '{{(index .IPAM.Config 0).Gateway}}'
```

For example, if it prints `172.17.0.1`, use `--host 172.17.0.1` for AI-Mode and
`MCP_HOST=172.17.0.1` for the MCP process. Keep Ollama on loopback: host AI-Mode
can reach it directly. Do not bind unauthenticated MCP CRUD to a public interface.
For host CLI inspection of a bridge-bound MCP server, pass its URL explicitly,
for example `.venv/bin/python -m tripgenie_mcp inspect --url http://172.17.0.1:8012/mcp`.
DNS-rebinding protection allows the configured bind host as well as loopback
and `host.docker.internal`; it does not allow arbitrary Host values.

Start the integrated application:

```bash
docker compose --env-file shared/configuration/.env.example config --quiet
docker compose --env-file shared/configuration/.env.example up --build -d
```

Compose publishes Student 4's public API at `127.0.0.1:18008` and Student 1's at
`127.0.0.1:18001`, matching MCP provider defaults. Database services stay private.
All feature backends now reach host AI-Mode; there is no AI-Mode Compose service.
MCP and RAG likewise stay outside Compose. This change does not implement the
separate Student 4 RAG UI or shared validation-loop modes.

Open `http://localhost:8084` and ask an activity question. Expand **Tools used**
to inspect the actual calls, filters, results and timings. Optional selected-trip
reads use existing `trip_get_context` and `trips_list_itinerary_items` MCP tools.
Ordinary browsing and CRUD continue working if AI-Mode or MCP is unavailable.

## Demonstration and evidence

1. Run the shared MCP `inspect` command and call `activities_list_categories`
   from a terminal as documented in its README.
2. Ask the frontend for accessible outdoor activities under a price limit.
3. Show returned activity cards and expand **Tools used**. It lists the real
   search and detail calls, rather than a model-generated claim of MCP usage.
4. Show the request/correlation ID in the backend trace and provider request logs.
   Request IDs propagate in `X-Request-ID` across backend, MCP and public API.
   Backend logs include tool/status/timing; application-specific HTTP access
   logs may not display custom headers without explicit logging configuration.
5. Show **Add to itinerary** opening the existing review action; the assistant
   itself never writes. An external CRUD demo is optional, not a rubric mandate.
6. Stop MCP and submit another question. Show the explicit unavailable response,
   then show ordinary catalogue browsing still works. There is no fallback to
   direct API search inside the assistant.

Keep report evidence under `docs/reports/release-1/Student4/`. A deterministic
model fixture proves protocol wiring and rendering but is not a live-model demo.
Record RAG evidence and shared agentic-loop validation separately when implemented.

## Checks

```bash
.venv/bin/pytest student-4/tests -q
.venv/bin/pytest ai-services/mcp-server/tests -q
.venv/bin/ruff check student-4 ai-services/mcp-server
.venv/bin/ruff format --check student-4 ai-services/mcp-server
.venv/bin/mypy --config-file student-4/pyproject.toml student-4/backend/student4_backend_service student-4/database/student4_database_service student-4/frontend/student4_frontend_service student-4/tests/backend student-4/tests/database student-4/tests/frontend student-4/tests/e2e
docker compose config --quiet
```

Student 4 CI explicitly disables runtime MCP and RAG modes. The separate MCP
contract job tests real SDK protocol sessions using fake provider/model transports,
including the full frontend/backend/MCP/card flow, without requiring host services.

### Instruction separation and request quality

The assistant sends its trusted prompt asset in AI-Mode's optional `system` field.
The question, registered tool descriptions/schemas and observations stay in `prompt`;
both fields share the existing character budget. This remains a one-shot workflow,
with no retained conversation. The prompt asks for clarification when essential
context is missing or constraints conflict, and explicitly refuses writes. Price
filters compare listed prices; party budgets additionally require evaluating the
returned pricing basis and party size. These are model instructions, not guarantees;
backend read-only enforcement and activity provenance checks remain authoritative.
