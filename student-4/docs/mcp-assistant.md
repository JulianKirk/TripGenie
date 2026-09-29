# Activity assistant through shared generation

The frontend calls its backend, which sends the question, optional selected trip,
trusted system prompt and final-answer schema to shared AI-Mode `/generate`.
AI-Mode discovers the complete shared MCP catalogue and runs the model/tool loop.
The model interprets requirements, selects tools and writes its answer. Student 4
only validates the response, resolves grounded activity cards and displays the trace.

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

Use a generation model with native tool support. Ollama, AI-Mode and MCP run on
the host, outside Compose. In separate terminals on Docker Desktop:

```bash
AI_MODE_DEFAULT_MODEL=qwen2.5:7b AI_MODE_ALLOWED_MODELS=qwen2.5:7b AI_MODE_TIMEOUT_SECONDS=90 AI_MODE_MCP_URL=http://127.0.0.1:8012/mcp .venv/bin/uvicorn ai_mode_service.app:app --host 0.0.0.0 --port 8006
.venv/bin/python -m tripgenie_mcp serve
```

Restrict AI-Mode access to the local application. On native Linux, bind AI-Mode to
an interface reachable through Docker's host gateway (for example the bridge
address printed by `docker network inspect bridge`), and restrict access using
host networking/firewall configuration. MCP can bind loopback because AI-Mode is
also a host process; feature containers no longer connect directly to MCP.
Example environment files are documentation and are not automatically loaded by
host processes. See [AI-Mode configuration](../../ai-services/ai-mode/README.md).

```bash
docker compose --env-file shared/configuration/.env.example config --quiet
docker compose --env-file shared/configuration/.env.example up --build -d
```

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
