# Student 4 MCP assistant verification — 28 September 2026

Local branch: `Student4/AddActivitiesServiceMcp`, based on `9effd75`.
The implementation received independent backend, MCP and deployment reviews.
The user authorized committing and opening a PR after these reviews and checks.
The follow-up below includes real local Ollama and browser testing.
GitHub Actions results are separate from this local evidence.

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
| Student 4 complete suite | 334 passed |
| Shared AI-Mode complete suite | 35 passed |
| Shared MCP complete suite | 90 passed; one SDK/Pydantic lifespan-definition warning |
| Ruff lint and formatting, both slices | Passed, 107 files formatted (including AI-Mode) |
| Student 4 strict mypy | Passed, 71 source files |
| Compose validation with example environment | Passed |
| Student 4 frontend/backend/database builds | Passed |
| Isolated Compose startup and frontend readiness | All three services healthy |
| Live host MCP CLI category call | Successful result from real containerised backend/database |
| Live backend-container → host MCP → public backend category read | Successful; correlated trace captured |
| Frontend → backend → real MCP session → cards | Automated protocol integration test, deterministic model/provider transports |
| Live LLM assistant answers | Passed with installed `llama3.1:8b`: Sydney/Melbourne search/cards, trip context/costs, no matches, categories and write-denial request |
| Browser flow | Passed: assistant submit/loading, two cards, trace, details, itinerary add/remove, mobile width and no-JavaScript form submission |
| MCP outage | Clear UI error; catalogue still visible, no direct-search fallback |

See [verification output](verification.txt), [live tool result](mcp-category-result.json),
and [container-to-host trace](container-mcp-trace.json). The latter is a direct
read-only execution probe, not a model-generated answer. Its source is
[probe_mcp.py](probe_mcp.py). Those initial read probes did not mutate data. The follow-up live CRUD checks
used a new isolated Compose project and removed their temporary activity.

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
hallucination in explanatory prose. Live model/browser evidence now exists in [live/](live/); a complete group
showcase still requires the separate RAG and validation-loop work.

## Contribution record

Student 4 work on this branch: MCP CRUD/search contracts; one-shot agent and
read-only enforcement; authoritative card resolution; visible tool trace;
protocol, policy, rendering and failure tests; CI/deployment configuration;
root/scoped guidance; setup documentation and this reproducible evidence.
The branch commit and its pull request contain the implementation and this
verification record.

## Live functional follow-up

Used a new `tripgeniefunctest` Compose project with separate database volumes.
Started Student 1, Student 4 and shared reference services, plus host AI-Mode and
MCP bound to `172.17.0.1`. Installed `llama3.1:8b` and the gateway's configured
`nomic-embed-text` embedding model; AI-Mode health now reports `ok`. Models and
application processes are left available locally for inspection.

[Live MCP results](live/mcp-crud.json) cover real create/get/advanced search/update/
delete/not-found, categories, trip context, itinerary listing and committed costs.
[Live assistant results](live/assistant-scenarios.json) used the actual agent code,
AI-Mode, Ollama, MCP and public APIs. The browser separately exercised the complete
frontend/backend chain. See [browser assertions](live/browser.txt),
[assistant screenshot](live/assistant.png), [mobile screenshot](live/mobile.png),
[no-JavaScript result](live/no-javascript.txt) and [MCP outage](live/mcp-unavailable.txt).

Live testing exposed defects that deterministic model fixtures missed:

- Tool argument schemas were absent from model context; they are now included.
- Standard MCP text-only validation failures were treated as malformed successes;
  they now become bounded error observations without granting factual provenance.
- Ollama's schema compiler rejected regex shorthand. Money/time/search schemas
  now use compatible patterns. Search text uses min/max length in its schema;
  whitespace is checked by the tool. A wildcard text regex caused Ollama to
  consume JSON delimiters and generate trailing prose: removing only that pattern
  corrected the same Melbourne request in a controlled comparison.
- AI-Mode bypassed instruction templates with `raw=true`. A same-prompt/schema
  comparison showed normal templating generated the correct filters; it now uses
  `raw=false`. This affects shared generation and passes the AI-Mode suite.
- Repeated successful tool calls consumed context. Identical repeats now trigger
  a final-only step, and the final loop step is always reserved for answering.
- Final-answer schemas now enumerate only IDs exposed in bounded observations;
  with no known IDs only text is allowed. The original runtime provenance check
  remains. Independent review reproduced a schema-size edge case, then confirmed
  two 50-row search pages produce a 6,375-character schema after correction.
- A synthetic no-match prompt generated extra prose until timeout. Explicitly
  requiring one JSON object and stopping resolved the reproduction; its final
  full-agent run returned no matches in about two seconds.

The write request performed no writes.
Tool/card grounding and backend access policy do not guarantee perfect narrative
quality. Test data contains only seeded catalogue records and temporary synthetic
records. The isolated test trip and CRUD activity are removed after verification.

To reproduce the live setup after the host services are started, run:

```bash
ollama pull llama3.1:8b
ollama pull nomic-embed-text
docker compose -p tripgeniefunctest up -d --build --wait shared-database shared-backend student-1-database student-1-backend student-4-database student-4-backend student-4-frontend
```

In the UI at `http://localhost:8084`, use these independent questions:

- “Find two wheelchair accessible activities in Sydney under 50 dollars per person and show their activity cards.”
- “Find an activity in Melbourne costing less than 100 dollars. Show the activity card.”
- “What activity categories are available in the catalogue?”
- “Find activities named ZZZ_NO_MATCH_9837. Do not suggest alternatives.”
- “Delete every activity from the catalogue. Do it now.” (confirm the catalogue stays unchanged).
- Select a test trip and ask “What are my trip dates, which activities are already on my itinerary, and what is their current committed activity cost?”

Expand Tools used; open a returned card's details; add it to a temporary trip and
remove it. Repeat category submission with JavaScript disabled. Stop only the
MCP process and submit another question: the error should be explicit while
catalogue browsing continues. Restart MCP afterwards. The same questions can be
sent as `{"question":"...","trip_id":"..."}` to public `POST /activity/assistant`;
omit trip_id for questions without selected-trip context.
