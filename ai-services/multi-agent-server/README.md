# TripGenie Multi-Agent Server (Release 2)

One shared, non-containerised server that runs a **Planner → Worker → Reviewer
→ Human Review** workflow for every feature. It runs on the host at
`http://127.0.0.1:8013`, its agents run on the shared AI-Mode gateway, and the
Worker uses the shared MCP tools through AI-Mode. It is never a Compose
service.

- Contract: [`docs/architecture/release-2-multi-agent-contract.md`](../../docs/architecture/release-2-multi-agent-contract.md)
- Decision record: [ADR 0005](../../docs/architecture/decisions/0005-shared-multi-agent-server.md)

| Agent | Does | AI-Mode call |
| --- | --- | --- |
| Planner | Writes the plan: goal, steps, required evidence, tools, success criteria | `/generate-plain` + plan schema + `tool_catalogue` (sees its feature's tool descriptions and arguments; cannot run them) |
| Worker | Carries out the plan with the feature's own prompt and MCP tools | `/generate` (model-directed MCP tool loop) + the feature's schema |
| Checks | Schema, tool grounding, allowed tools, no writes, tool evidence | none (deterministic) |
| Reviewer | Judges the result against the plan, evidence and checks; lists risks | `/generate-plain` + review schema |
| Human | Approves, corrects, partially accepts or rejects | `POST /runs/{id}/review` |

When the Reviewer asks for a revision, a check fails, or the Worker's call
fails because the model got its tool calls wrong (AI-Mode `BAD_GATEWAY`), the
run goes back to the Planner with the previous attempt (plan, tool calls and
their errors, failed checks, review) and then to the Worker again, once by
default. Outages and timeouts are not retried, and an attempt that ran a
write tool is never repeated.

## Run it

```bash
cd ai-services/multi-agent-server
python -m pip install -e ".[dev]"
python -m multi_agent_service serve          # 127.0.0.1:8013
curl http://127.0.0.1:8013/ready             # needs AI-Mode on :8006
```

`scripts/run-app.sh` starts it with the other host services. Run history is
kept in `data/runs.sqlite3` (git-ignored; override with `MULTI_AGENT_DB_PATH`).

## Use it from the terminal

```bash
python -m multi_agent_service run --feature student-3 \
  --task "What is the cheapest way to get from Melbourne to Sydney for two travellers?"
#   prints each stage as it finishes, then asks: 1 Approve · 2 Correct ·
#   3 Partially accept · 4 Reject
python -m multi_agent_service list --feature student-3
python -m multi_agent_service show <run_id>
python -m multi_agent_service review <run_id> --decision approve --reviewer <name>
python -m multi_agent_service export <run_id> --format markdown --output run.md
```

Terminal runs use a generic answer schema (`answer` plus grounded `items`)
and MCP-owned feature membership selected by `--feature`. The obsolete `--tool`
selector is rejected by the CLI. Pass
`--decision` and `--reviewer` to run without prompts, or `--no-review` to stop
at `awaiting_human`.

## Use it from a feature backend (integration kit)

### 1. Settings and Compose

Add, following the existing AI-Mode/MCP/RAG pattern (`N` = your student
number):

```yaml
# docker-compose.yml, under studentN-backend.environment
STUDENTN_BACKEND_MULTI_AGENT_ENABLED: "${STUDENTN_BACKEND_MULTI_AGENT_ENABLED:-true}"
STUDENTN_BACKEND_MULTI_AGENT_BASE_URL: http://host.docker.internal:8013
STUDENTN_BACKEND_MULTI_AGENT_TIMEOUT_SECONDS: "15"
```

The backend already has `extra_hosts: ["host.docker.internal:host-gateway"]`.
Set `STUDENTN_BACKEND_MULTI_AGENT_ENABLED=false` in your `student-N-ci.yml`
and in the cloud deployment (Release 2 cloud baseline), and return a clear
`503 MULTI_AGENT_DISABLED` from your routes when it is off.

### 2. Start a run

The request carries your own prompt, schema, tools and grounding rule, so your
feature keeps owning its domain logic:

```python
response = httpx.post(
    f"{base_url}/runs",
    json={
        "feature": "student-3",
        "task": question,  # ≤ 500 chars
        "trip_id": trip_id,  # optional
        "context": {"first_search": {"limit": 12}},  # your prompt's own fields
        "worker_system": load_prompt("transport_agents_v1.md"),
        "output_schema": MyDraft.model_json_schema(),
        "grounding": {
            "source": "student-3",
            "id_paths": ["suggestions[].transport_id"],
        },
        "actions_path": "actions",  # optional
        "correlation_id": f"student3-agents-{uuid4().hex[:12]}",
        "metadata": {"service": "student-3-backend"},
    },
    timeout=15,
)
run = response.json()["data"]  # 202, status "planning"
```

Write `worker_system` the way you write an AI-Mode prompt: a role, "Use the
native MCP functions … actually invoke them", which tool to call first and
with which `context` fields. The server appends its own workflow rules after
it; keep your instructions first (see ADR 0005).

For rules needed by every role, send optional `feature_instructions` alongside
`worker_system`. Use concise domain policy (for example, one-shot interaction and
group-price semantics), not Worker JSON formatting or tool-execution commands.
Planner and Reviewer receive it in their system prompts on every attempt and
retain their own roles and schemas. Keep the complete Worker policy in
`worker_system`; the server does not append these rules again or change that
prompt's order. This keeps Worker context concise and preserves the feature's
execution instructions. The two fields share the 6,000-character limit, and
Planner/Reviewer stage budgets count the common rules. Omitting it
preserves existing behavior. Upgrade the shared server before a feature starts
sending the field; older servers reject it as unknown. Trusted feature backends
load these instructions from assets, never from user request text.

The server forwards `feature` to AI-Mode for each agent. MCP owns feature
membership; callers do not supply tool lists. `allowed_tools` is accepted only
for older clients/stored requests and does not select availability. Each stage
records `available_tools` from AI-Mode; the Planner uses its catalogue snapshot
and deterministic tool checks use the Worker's snapshot. Tool evidence remains
required. Upgrade MCP and AI-Mode before the Multi-Agent Server.

### 3. Poll and show each stage

`GET /runs/{run_id}` is cheap; poll every 2 s from the UI (HTMX:
`hx-get="…" hx-trigger="every 2s"` until the status is `awaiting_human`,
`completed`, `rejected` or `failed`). Show, as they arrive:

- the Planner's `plan.goal` and `plan.steps`;
- the Worker's tool calls (`steps[].tools`, the same trace shape as AI-Mode,
  so your existing "Tools used" partial works) and `result`;
- every `checks[]` entry, highlighting any that failed;
- the Reviewer's `review.verdict`, `summary`, `risks` and `recommendations`.

Re-read any record ids in `result` from your own database before showing them,
exactly as you do for AI-Mode answers.

### 4. Record the human decision, then act on it

```python
httpx.post(
    f"{base_url}/runs/{run_id}/review",
    json={
        "decision": "approve",  # approve · correct · partial · reject
        "reviewer": "traveller",
        "notes": "Looks right",
        # "corrected_result": {...}   # for correct (validated against your schema)
        # "accepted_actions": [0]     # for partial
    },
)
```

The response's `approved_actions` are the changes the human accepted. **The
Multi-Agent Server never writes your data**: perform them through your own
routes (Student 3, for example, adds an approved option to a trip through its
existing itinerary route).

### 5. Test without live services

Inject an `httpx.MockTransport` into your client and return canned run records,
exactly as you fake AI-Mode today. A minimal fake:

```python
def fake_multi_agent(request: httpx.Request) -> httpx.Response:
    if request.method == "POST" and request.url.path == "/runs":
        return httpx.Response(
            202,
            json={
                "data": {
                    "run_id": "magent_000000000001",
                    "status": "planning",
                    "steps": [],
                }
            },
        )
    if request.url.path.endswith("/review"):
        return httpx.Response(200, json={"data": {**AWAITING, "status": "completed"}})
    return httpx.Response(200, json={"data": AWAITING})  # a stored awaiting_human run
```

`multi_agent_service.client.MultiAgentClient` is a complete synchronous client
you can copy into your backend package (services integrate over HTTP; do not
import this package from a feature).

## Errors

Validation failures are `422 VALIDATION_ERROR` with field details, an unknown
run is `404 RUN_NOT_FOUND`, a decision on a run that is not awaiting one is
`409 RUN_NOT_AWAITING_REVIEW`, and a full server is `503 RUN_LIMIT_REACHED`.
Stage failures do not return errors: the run ends `failed` with `error.code`
and the steps it completed (see the contract).

## Checks

From the repository root:

```bash
python -m pip install -e "./ai-services/multi-agent-server[dev]"
python -m compileall ai-services/multi-agent-server/multi_agent_service ai-services/multi-agent-server/tests
ruff check ai-services/multi-agent-server
ruff format --check ai-services/multi-agent-server
pytest ai-services/multi-agent-server/tests -q
```

The tests use a fake AI-Mode behind an injected transport and a temporary
SQLite file; they need no Ollama, MCP server or feature backend. CI runs them
in `.github/workflows/multi-agent-ci.yml`.
