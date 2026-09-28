# Student 4 MCP assistant verification — 28 September 2026

Local branch: `Student4/AddActivitiesServiceMcp`, based on `9effd75`.
The implementation received independent backend, MCP and deployment reviews.
The user authorized committing and opening a PR after these reviews and checks.
No GitHub Actions result or live LLM demonstration is claimed by this local evidence.

## Scope verified

- Full activity CRUD and advanced search exposed as typed MCP tools.
- Frontend activity assistant uses an explicit backend read allowlist and
  request-local state. It renders authoritative cards and actual execution traces.
- Shared trip tools were already present; this change permits selected-trip use.
- Root/scoped agent guidance and host-service deployment configuration updated.
- Runtime MCP disabled in CI while contract/protocol tests use deterministic
  provider/model transports. RAG UI and shared agentic-loop modes are separate work.

## Results

| Check | Result |
| --- | --- |
| Student 4 complete suite | 329 passed |
| Shared MCP complete suite | 89 passed; one SDK/Pydantic lifespan-definition warning |
| Ruff lint and formatting, both slices | Passed, 95 files formatted |
| Student 4 strict mypy | Passed, 71 source files |
| Compose validation with example environment | Passed |
| Student 4 frontend/backend/database builds | Passed |
| Isolated Compose startup and frontend readiness | All three services healthy |
| Live host MCP CLI category call | Successful result from real containerised backend/database |
| Live backend-container → host MCP → public backend category read | Successful; correlated trace captured |
| Frontend → backend → real MCP session → cards | Automated protocol integration test, deterministic model/provider transports |
| Live LLM assistant answer | Not run: local Ollama `/api/tags` returned an empty models list |

See [verification output](verification.txt), [live tool result](mcp-category-result.json),
and [container-to-host trace](container-mcp-trace.json). The latter is a direct
read-only execution probe, not a model-generated answer. Its source is
[probe_mcp.py](probe_mcp.py). No live create/update/delete operations were used.

## Reproduction

From the repository root, install Python 3.11 dependencies as described in
`student-4/docs/mcp-assistant.md`, then run:

```bash
.venv/bin/pytest student-4/tests -o addopts='' -q
.venv/bin/pytest ai-services/mcp-server/tests -q
.venv/bin/ruff check student-4 ai-services/mcp-server
.venv/bin/ruff format --check student-4 ai-services/mcp-server
.venv/bin/mypy --config-file student-4/pyproject.toml student-4/backend/student4_backend_service student-4/database/student4_database_service student-4/frontend/student4_frontend_service student-4/tests/backend student-4/tests/database student-4/tests/frontend student-4/tests/e2e
docker compose --env-file shared/configuration/.env.example config --quiet
STUDENT4_MCP_ENABLED=false docker compose -p student4mcpverify up -d --build --no-deps --wait student-4-database student-4-backend student-4-frontend
curl --fail http://127.0.0.1:8084/ready
```

On this native Linux host the Docker bridge address is `172.17.0.1`. Run MCP in
another terminal, then perform the read probes:

```bash
MCP_HOST=172.17.0.1 .venv/bin/python -m tripgenie_mcp serve
# Separate terminal:
.venv/bin/python -m tripgenie_mcp call activities_list_categories --url http://172.17.0.1:8012/mcp
docker compose -p student4mcpverify exec -T student-4-backend python - < docs/reports/release-1/Student4/probe_mcp.py
```

The application MCP mode is intentionally disabled for the isolated CI-like
smoke. The direct probe exercises connectivity without invoking AI-Mode.
Shared-location and itinerary services are not started in this smoke; full
catalogue/trip interaction is covered by tests, not claimed as live evidence.
The probe does not use the disabled public assistant endpoint.

Stop only this newly created verification project's containers and test volumes
after collecting evidence. The host MCP process is also stopped after testing.

## Review corrections and limitations

An independent review found a mismatch between public HH:MM times and MCP's
advertised JSON schema. A failing registered-schema regression test reproduced
it; the MCP schema now advertises the exact HH:MM pattern. A bridge-host protocol
test additionally verifies DNS-rebinding validation accepts the configured bind
address without allowing arbitrary hosts. The Docker smoke caught missing
backend image dependencies; the standalone backend package now includes them.

A final independent review identified four further corrections: the agentic
Compose overlay duplicated the new Student 4 host port; host AI-Mode startup
omitted the prior inference timeout; oversized activity writes could commit before
the response cap rejected their acknowledgement; and duplicate activity references
could bypass the six-card limit. All were corrected. Regression tests reproduced
the port, write and card defects before the fixes; the MCP reviewer rechecked the
write-size correction. The startup recipe now explicitly sets a 90-second timeout.

SQLAlchemy 2.1 changed Select typing and broke the unchanged repository's strict
mypy checks under the previous `<3.0` range. Student 4's aggregate/database package
requirements now target the existing supported 2.0 API (`>=2.0,<2.1`); final tests
and typing use 2.0.54. No database logic or assertions were weakened.

External MCP write access remains for trusted local clients; there is no new
user-authentication system. Frontend agent write denial is enforced separately
by code. Typed cards prevent invented catalogue records, not every possible
hallucination in explanatory prose. A suitable installed local model and the
remaining group services are still required for the final showcase video.

## Contribution record

Student 4 work on this branch: MCP CRUD/search contracts; one-shot agent and
read-only enforcement; authoritative card resolution; visible tool trace;
protocol, policy, rendering and failure tests; CI/deployment configuration;
root/scoped guidance; setup documentation and this reproducible evidence.
The branch commit and its pull request contain the implementation and this
verification record.
