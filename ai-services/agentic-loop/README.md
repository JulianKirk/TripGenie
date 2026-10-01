# Agentic loop

PLAN -> ACT -> OBSERVE -> AGENTS -> HUMAN -> ADAPT, shared by every TripGenie
service. The deterministic half is a JSON checks file; the agent half is two
Claude calls that comment on the evidence. Only the deterministic half decides
the exit code.

## Checks files

One per service, in `checks/`: `shared.json` and `student-1.json` .. `student-5.json`.
Each targets `${SERVICE_URL}`, so the same file works wherever the service is
published.

```json
{"goal": "...", "checks": [{"label": "GET /health", "path": "${SERVICE_URL}/health"}]}
```

Check fields: `label`, `path` (`${VARS}` expand from the environment, so a file
can also span services), `method`, `status` (default 200), `form`/`json` body,
`contains` (substrings the body must have), `nfr_ms` (latency budget, 95% of 20
samples must be under it), `timeout`.

### Business processes

A single endpoint answering `200` is not the same as the service getting the
job done. `flows` are the second half: ordered steps that feed each other, and
`invariants` -- the domain rules -- computed over what they collected.

```json
"flows": [
  {
    "name": "Budget to expenses arithmetic",
    "steps": [
      {"label": "GET /budgets (pick one)", "path": "${BACKEND_URL}/api/v1/budgets",
       "save": {"BUDGET_ID": "data.0.budget_id", "TRIP_ID": "data.0.trip_id"}},
      {"label": "GET that budget's summary", "path": "${BACKEND_URL}/api/v1/budgets/${BUDGET_ID}/summary",
       "contains": ["${TRIP_ID}"], "save": {"TOTAL": "data.total_budget"}}
    ],
    "invariants": [
      {"label": "remaining = total - spent - committed",
       "expr": "abs(float(REMAINING) - (float(TOTAL) - float(SPENT) - float(COMMITTED))) < 0.01"}
    ]
  }
]
```

A step is an ordinary check plus `save`: `{NAME: "dotted.path.into.the.body"}`,
where a digit indexes a list. `${NAME}` then expands anywhere in a later step --
path, query string, JSON body, `contains` -- so a flow asserts things one
request cannot: that a search returns a record the detail endpoint agrees with,
that filtering by a record's own field still returns it, that a derived total is
actually derived. The first failing step stops the flow; the rest report `SKIP`
and so do the invariants, because their inputs were never collected.

`invariants` are `{"label", "expr"}`, evaluated over the saved values with
`float`, `abs` and `len` available and nothing else. A false expression is a
failed check like any other.

`rules` is the third addition, and it is for the agents rather than the checks:
the domain facts they must not contradict ("subject_code is not unique", "this
service is read-only"). They go into the scope both prompts receive, next to
the endpoint and flow labels, which is what stops a reviewer recommending a
unique constraint on a column that must not have one.

Student 4's loop starts the normal `student-4` Compose grouping target with its
transitive dependencies. This lets its public catalogue flows resolve shared
locations and reach the same service graph used by the integrated application,
rather than reviewing an intentionally degraded three-container slice. Ollama
remains host-managed; AI checks must accept its documented unavailable state
when no model runtime is configured on the machine.

## Run it

```bash
pip install -r requirements.txt
docker compose -f ../../docker-compose.yml -f docker-compose.agentic.yml \
  up -d --build student-1-backend
SERVICE_URL=http://127.0.0.1:8001 CHECKS_FILE=checks/student-1.json python agentic_loop.py
```

The overlay publishes the internal-only Student 3, Student 4, and Student 5
backends while the loop runs. They remain private in the main Compose file.

`--ci` skips the human-review prompt.

Several services in one run -- the loop waits for each one's
readiness itself, reports a service that never becomes ready as failed in its
own section, and marks the rest skipped:

```bash
SERVICES="student-1 student-3" python agentic_loop.py --ci --mode services
```

## Modes

`--mode {services,mcp,rag,ci}` picks what the collector observes. Run with no
flag in a terminal and the loop shows a menu instead (`0` exits); `--ci` without
`--mode` runs `services`, so existing invocations are unchanged. Every mode ends
the same way: the two agents comment, and only the collector's checks decide
the exit code.

| Mode | Collector | Checks file |
| --- | --- | --- |
| `services` | HTTP checks against running backends | `checks/<service>.json` |
| `mcp` | JSON-RPC tool calls to the host MCP server | `checks/mcp.json` |
| `rag` | Calibration queries to the host RAG server | `checks/rag.json` -> `../rag-server/config/calibration-queries.json` |
| `ci` | Latest `student-x-ci.yml` run per service via `gh` | `checks/ci.json` |

**MCP** (`python -m tripgenie_mcp serve` plus the five backends, started with the agentic overlay): all 19 tools
are listed (the three activity write tools are listed, never called); one valid read per student returns `ok: true`, `data` and the right
`source`; IDs and amounts match the same backend read directly; `limit: 0`, a
malformed ID and an unknown tool are rejected; each call repeats with the same
data and finishes under 3 s. Steps chain with `save` like flows do. Direct
backend reads use the MCP server's own `MCP_STUDENT_n_URL` variables and
defaults (loopback ports 18001/9000/18003/18008/18005). Compose does not yet
publish student 3 on 18003 -- the agentic overlay uses 8003 -- so set
`MCP_STUDENT_3_URL=http://127.0.0.1:8003` for both processes until it does.

**RAG** (AI-Mode plus `python -m rag_service serve` with a built index): every
answerable calibration case returns an answer, a confidence category and its
`expected_source_ids`; the unanswerable one returns insufficient context; a
repeat returns the same citations and category; insufficient context comes back
under 3 s and answers under 30 s. The cases live in the RAG server's own
calibration file, so there is one list to maintain.

**CI** (`gh auth login` first): for the current branch (`CI_BRANCH` overrides),
the latest run of each service's workflow becomes a check -- `success` passes,
any other conclusion fails, no run is a skip -- and its artifacts are downloaded
to `reports/ci/<service>/`. Without `gh` the mode reports that and passes.

| Variable | Default |
| --- | --- |
| `SERVICES` / `SKIPPED` | unset -- use `CHECKS_FILE`; `SKIPPED` is `service=reason;...` |
| `MCP_URL` | `http://127.0.0.1:8012/mcp` |
| `RAG_URL` | `http://127.0.0.1:8011` |
| `CI_BRANCH` | the checked-out branch |

Each mode has its own agent prompts in `prompts/<mode>/`, following the labs:
`services` reviews endpoints and flows; `mcp` has the implementation agent pick
a tool for each `tool_selection` request in `checks/mcp.json` (Lab 7) -- scored
as advisory `NOTE` rows that never fail the run -- and the reviewer answers
Strengths / Risks / Recommendations; `rag` reviews output quality and the
architecture together (Lab 8); `ci` proposes one pipeline improvement and the
reviewer approves it or raises a risk (Lab 5).

Every run saves its report to `reports/<mode>-<UTC timestamp>.md` (git-ignored).
Copy the ones the release needs into `docs/reports/release-*`.

The two agents call Claude. Credentials come from the environment the way the
`anthropic` SDK resolves them -- `ANTHROPIC_API_KEY`, or an `ant auth login`
profile locally. The implementation agent defaults to `claude-sonnet-5` and the
reviewer to `claude-opus-5`; the reviewer checks the recommendation, so it is
the more capable of the two. Override either with `IMPLEMENTATION_MODEL` /
`REVIEW_MODEL`. With no credentials the agent sections print "unavailable" and
the run still passes or fails on the checks.

## Local only

The loop is not part of CI -- no workflow runs it or its unit tests. Run it on
your machine, where the services, the host MCP and RAG servers, Ollama and
your Claude credentials already are. A full Release 1 run:

```bash
docker compose -f ../../docker-compose.yml -f docker-compose.agentic.yml up -d --build
python agentic_loop.py --ci --mode services   # with SERVICES="shared student-1 ..." for all of them
python agentic_loop.py --ci --mode mcp        # MCP server running
python agentic_loop.py --ci --mode rag        # Ollama, AI-Mode, MCP and RAG running
python agentic_loop.py --ci --mode ci         # gh auth login first
pytest -q                                     # the loop's own tests
```

RAG answers need the MCP server as well: AI-Mode's `/generate` runs its tool
loop against it, so start MCP before `--mode rag`.

## Where the findings go

Each run prints PLAN -> ACT -> OBSERVE -> AGENTS -> HUMAN -> ADAPT to stdout
and saves the same check tables and agent sections to
`reports/<mode>-<UTC timestamp>.md`. Without `--ci` it also asks for the human
review decision.

Findings are advisory. Only the deterministic checks set the exit code, so a
broken or unauthenticated Claude call cannot fail a run -- and equally, cannot
block it. Read the report, don't just trust the exit code.
