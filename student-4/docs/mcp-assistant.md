# Activity assistant through shared generation

The frontend calls its backend, which sends the question, optional selected trip,
trusted system prompt and final-answer schema to shared AI-Mode `/generate`.
AI-Mode discovers the complete shared MCP catalogue and runs the model/tool loop.
The model interprets requirements, selects tools and writes its answer. Student 4
only validates the response, resolves grounded activity cards and displays the trace.
The superseded plan/evaluate endpoints, their two prompt assets and their parser
have been removed. `activity_assistant_v1.md` is the sole Student 4 AI prompt.

All advertised tools are available, including other students' tools and activity
create/update/delete. Prompts direct writes only when requested; there is no hard
read-only guarantee. Inspect tool results for actions completed, even after a failure.
No conversation history is retained. Ordinary browsing and CRUD work without AI.

## Local setup

From the repository root with Python 3.11:

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -e './student-4[dev]' -e './ai-services/ai-mode[dev]' -e './ai-services/mcp-server[dev]'
ollama pull qwen2.5:7b
ollama pull nomic-embed-text
```

Use a generation model with native tool support. AI-Mode runs in Compose;
Ollama and MCP run on the host. On native Linux, obtain Docker's host-gateway
address with `docker network inspect bridge` (typically `172.17.0.1`). Start MCP
on that interface, for example:

```bash
MCP_HOST=172.17.0.1 .venv/bin/python -m tripgenie_mcp serve
```

On Docker Desktop, use a host binding reachable through `host.docker.internal`
(such as `MCP_HOST=0.0.0.0`) and restrict access to the local application with the
host firewall. Ollama must likewise listen on a Docker-accessible host interface.
Keep an existing host-managed Ollama process; configure its binding instead of
starting a second instance. AI-Mode connects to host ports 11434 and 8012.

Example environment files are not automatically loaded by host processes.
See [AI-Mode configuration](../../ai-services/ai-mode/README.md).
To use the tool-capable Qwen model for the demonstration:

```bash
docker compose --env-file shared/configuration/.env.example config --quiet
AI_MODE_DEFAULT_MODEL=qwen2.5:7b AI_MODE_ALLOWED_MODELS=qwen2.5:7b,llama3.1:8b docker compose --env-file shared/configuration/.env.example up --build -d
```

Backends use `http://ai-mode:8006`; host RAG uses the loopback-published gateway
at `http://127.0.0.1:8006`. RAG's hosting and retrieval workflow are unchanged.

Compose publishes Student 4's public backend at `127.0.0.1:18008` and Student 1's
at `127.0.0.1:18001` for host MCP; databases remain private. Other tool providers
must be reachable at the URLs configured on MCP. An unavailable provider produces
an explicit tool error. All catalogue definitions are still discoverable.

## Functional checks

Open `http://localhost:8084`. Use the [showcase prompts](../../docs/reports/release-1/Student4/showcase-prompts.md):

- `Show me kayaking activities in Sydney.`
- `Find the Sydney Harbour sunrise kayak activity, then look up its full details and tell me its weekly schedule and booking notes.`

Expand **Tools used** and **Returned tool data**. Verify actual search/detail calls
and whether the answer accurately reflects those records. Card lookups use the
ordinary backend and do not appear as MCP calls. A missing model-selected detail
call is a model-quality failure, not a trigger for backend answer rewriting.
Also exercise natural-language budgets/dates, clarification, cross-domain tools,
ordinary catalogue actions and MCP outage/recovery. Use isolated test data for writes.

## Checks

```bash
.venv/bin/pytest student-4/tests -q
.venv/bin/pytest ai-services/ai-mode/tests -q
.venv/bin/pytest ai-services/mcp-server/tests -q
.venv/bin/ruff check student-4 ai-services/ai-mode ai-services/mcp-server
.venv/bin/ruff format --check student-4 ai-services/ai-mode ai-services/mcp-server
.venv/bin/mypy --config-file student-4/pyproject.toml student-4/backend/student4_backend_service student-4/database/student4_database_service student-4/frontend/student4_frontend_service student-4/tests/backend student-4/tests/database student-4/tests/frontend student-4/tests/e2e
docker compose config --quiet
```

Keep development evidence outside the repository. Protocol fakes establish wiring,
not live-model answer quality. Do not reintroduce natural-language parsers, forced
retrieval or authored answer replacement to improve showcase results.
