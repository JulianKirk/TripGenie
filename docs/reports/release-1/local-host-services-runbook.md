# Release 1 local host services runbook

Release 1 runs AI-Mode, RAG, MCP, Ollama, and the agentic loop as host
processes. Docker Compose runs only the shared reference service and the
feature frontends, backends, and databases. Backends reach the host through
`host.docker.internal`.

| Host process | Port | Container URL | Host URL |
| --- | --- | --- | --- |
| Ollama | 11434 | not used | `http://127.0.0.1:11434` |
| AI-Mode | 8006 | `http://host.docker.internal:8006` | `http://127.0.0.1:8006` |
| RAG | 8011 | `http://host.docker.internal:8011` | `http://127.0.0.1:8011` |
| MCP | 8012 | `http://host.docker.internal:8012/mcp` | `http://127.0.0.1:8012/mcp` |

MCP in turn calls the public backends Compose publishes on host loopback:
Student 1 `18001`, Student 2 `9000`, Student 3 `18003`, Student 4 `18008`,
Student 5 `18005`.

Commands below are for macOS/Linux shells from the repository root; on Windows
PowerShell set variables with `$env:NAME = "value"` instead. Host processes do
not read `shared/configuration/.env.example`; export what you need. Use Python
3.11 or later.

## Binding and firewall

- **Docker Desktop (macOS/Windows):** `host.docker.internal` forwards to the
  host, so the default `127.0.0.1` bindings normally work. If a container still
  cannot connect, bind the service to `0.0.0.0` and block its port from other
  networks with the host firewall.
- **Native Linux:** Compose's `host-gateway` mapping points
  `host.docker.internal` at the Docker bridge (`docker network inspect bridge`,
  typically `172.17.0.1`). A process on `127.0.0.1` is not reachable there.
  Bind AI-Mode, RAG, and MCP to `0.0.0.0` (or the bridge IP, then point host
  clients such as `RAG_AI_MODE_BASE_URL` at that IP too) and allow the Docker
  subnet while blocking 8006, 8011, and 8012 from external networks. None of
  these services has authentication.
- Ollama only needs loopback: AI-Mode is its sole caller and runs on the host.

## 1. Ollama and models

Keep one host-managed Ollama running; do not start a second instance.

```bash
ollama pull llama3.1:8b
ollama pull nomic-embed-text
curl http://127.0.0.1:11434/api/tags
```

## 2. AI-Mode (terminal 1)

```bash
cd ai-services/ai-mode
python -m pip install -e .
export AI_MODE_DEFAULT_MODEL=llama3.1:8b
export AI_MODE_ALLOWED_MODELS=qwen2.5:0.5b,llama3.1:8b
export AI_MODE_DEFAULT_EMBEDDING_MODEL=nomic-embed-text
export AI_MODE_TIMEOUT_SECONDS=90
export AI_MODE_MCP_URL=http://127.0.0.1:8012/mcp
python -m uvicorn ai_mode_service.app:app --host 127.0.0.1 --port 8006
```

Use `--host 0.0.0.0` where the binding notes above require it. The 90-second
timeout covers a cold 8b model; backend timeouts in Compose sit above it.

## 3. RAG ingest and serve (terminal 2)

```bash
cd ai-services/rag-server
uv sync --extra dev
uv run python -m rag_service ingest --rebuild
uv run python -m rag_service serve
```

Ingest needs AI-Mode embeddings only. Set `RAG_BIND_HOST` before `serve` for a
non-loopback binding. The index (`data/rag.sqlite3`) is git-ignored; rebuild it
after changing the embedding model or knowledge sources.

## 4. MCP server (terminal 3)

```bash
cd ai-services/mcp-server
python -m pip install -e ".[dev]"
python -m tripgenie_mcp serve
```

Set `MCP_HOST` for a non-loopback binding. AI-Mode `/generate`, and so RAG
answers, need MCP running.

## 5. Docker Compose

```bash
docker compose --env-file shared/configuration/.env.example config --quiet
docker compose --env-file shared/configuration/.env.example up --build -d
```

Containers start and pass their health checks whether or not the host services
are running; an unreachable host service disables only the AI, RAG, or MCP
feature. To turn Student 1's RAG or MCP client off explicitly, set
`STUDENT1_BACKEND_RAG_ENABLED=false` or `STUDENT1_BACKEND_MCP_ENABLED=false`
(Student 5 has matching `STUDENT5_BACKEND_*` flags).

## 6. Verify

```bash
curl http://127.0.0.1:8006/health
curl http://127.0.0.1:8006/ready
curl http://127.0.0.1:8011/health
curl http://127.0.0.1:8011/ready
curl http://127.0.0.1:8012/health
docker compose --env-file shared/configuration/.env.example ps
curl http://127.0.0.1:18001/ready
curl http://127.0.0.1:9000/health
curl http://127.0.0.1:18003/ready
curl http://127.0.0.1:18008/ready
curl http://127.0.0.1:18005/ready
```

Check the container-to-host path from inside a backend:

```bash
docker compose exec student-1-backend python -c "import urllib.request; print(urllib.request.urlopen('http://host.docker.internal:8006/health', timeout=5).read())"
```

Check that MCP reaches the published backends (from `ai-services/mcp-server`):

```bash
python -m tripgenie_mcp call transport_search '{"limit":5}'
python -m tripgenie_mcp call budgets_list '{"limit":5}'
```

Then open the portal at `http://localhost:8080` and exercise each feature's
AI, MCP, and RAG flows.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Port 8006 already in use | A Release 0 `ai-mode` container may still be running. `docker compose down --remove-orphans` (no `-v`) removes it. |
| Backend reports AI-Mode/RAG/MCP unavailable | The host process is stopped, or on Linux it listens on loopback only. Re-run the in-container check above. |
| `host.docker.internal` does not resolve | Docker Engine is older than 20.10 (no `host-gateway`), or the service lacks the `extra_hosts` entry. |
| AI-Mode `/health` is `degraded` | Ollama is not running or a configured model is not pulled; see step 1. |
| RAG `/ready` returns 503 | AI-Mode is not ready or the index is missing; re-run the ingest. |
| MCP tool returns `PROVIDER_UNAVAILABLE` | Compose is not up, or the backend's loopback port is not published (`docker compose ps`). |
| Linux: connections time out | The host firewall is dropping traffic from the Docker subnet to 8006/8011/8012. |

## Safe shutdown

1. Stop MCP, RAG, and AI-Mode with Ctrl-C in their terminals.
2. Stop the containers and keep all application data:

   ```bash
   docker compose --env-file shared/configuration/.env.example down
   ```

3. Leave Ollama and its models in place unless you want them gone.

`docker compose down -v` deletes every feature database volume; use it only
when a reset is intended. Avoid `docker system prune`, which also removes
unrelated Docker resources. To reset only the RAG index, re-run
`uv run python -m rag_service ingest --rebuild`.
