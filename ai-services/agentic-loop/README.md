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
when no model runtime is configured on the runner.

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

Several services at once, the way CI runs them -- the loop waits for each one's
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

Every run saves its report to `reports/<mode>-<UTC timestamp>.md` (git-ignored).
Copy the ones the release needs into `docs/reports/release-*`.

The two agents call Claude. Credentials come from the environment the way the
`anthropic` SDK resolves them -- `ANTHROPIC_API_KEY`, or an `ant auth login`
profile locally. The implementation agent defaults to `claude-sonnet-5` and the
reviewer to `claude-opus-5`; the reviewer checks the recommendation, so it is
the more capable of the two. Override either with `IMPLEMENTATION_MODEL` /
`REVIEW_MODEL`. With no credentials the agent sections print "unavailable" and
the run still passes or fails on the checks, so CI works either way (add
`ANTHROPIC_API_KEY` to the repository secrets to turn them on).

## In CI

`.github/workflows/agentic-ci.yml` runs on push and pull request as two jobs.
It runs the `services`, `mcp` and `rag` modes; `ci` stays local. MCP and RAG
are switched on only here -- each student's own CI keeps them disabled so a
student build never needs a model.

- **Loop unit tests** -- `pytest` on the loop itself. Always runs, starts no
  containers, and is the reason a change to `agentic_loop.py` still gets tested
  when every service below is skipped. One registry-contract test uses
  `docker compose config`, which is available on the GitHub runner.
- **Agentic loop** -- one job. Its first step is the gate: for each service it
  polls that service's own build-and-validate workflow for this commit and
  decides whether the loop runs. Compose then starts only the chosen services
  in one command, and the loop runs with `SERVICES` set to them and `SKIPPED`
  carrying the gate's reason for the rest. Any failed check fails the job.
  Then it starts the MCP server on the runner and runs `--mode mcp`, with the
  per-student reads limited to the services just started (tool registration
  and the validation probes always run). Finally it starts Ollama from the
  official image with `qwen2.5:0.5b` and `nomic-embed-text`, AI-Mode from
  Compose, builds the RAG index, starts the RAG server and runs `--mode rag`.
  MCP and RAG run even when no service was selected, and a change under
  `ai-services/ai-mode`, `mcp-server` or `rag-server` triggers the workflow.

| That service's workflow | This service |
| --- | --- |
| passed | loop runs |
| failed | skipped -- no point validating a build that did not pass |
| never started (its path filters skipped the commit) | skipped -- the service did not change |
| could not be read | loop runs ungated, rather than silently skipping validation |
| still running after 30 minutes | loop runs ungated |

The gate lists every workflow run for the commit in one call, so all six services
share a single two minute wait for workflows to appear -- a commit that changes
nothing clears the gate in about two minutes, not two minutes per service.

So an ordinary commit runs the loop for the one or two services it touched, not
all six, and the gate's verdict for every service is written to the run summary
as a table. When nothing was selected the summary says so outright:
"No services were changed - agentic loop skipped for all services."
"Run workflow" ignores the gate and runs everything.

One gap worth knowing: a change to the shared service does not trigger student 2's
CI, so student 2's loop skips even though it calls the shared backend. Integration
CI is what covers that direction.

## Where the findings go

Both agents' output is written to the job's **Summary** page (via
`GITHUB_STEP_SUMMARY`) as a check table plus the two agent sections -- not just
buried in the log. Locally it prints to stdout; `--ci` skips the human-review
prompt but not the printing.

On a pull request the workflow posts the services, MCP and RAG reports as one
comment, edited in place on later pushes rather than appended, so a busy pull
request does not fill with tables. It posts whether the loop passed or failed,
and says nothing at all when the commit is not on an open pull request.

Findings are advisory. Only the deterministic checks set the exit code, so a
broken or unauthenticated Claude call cannot fail the build -- and equally,
cannot block it. Read the summary, don't just trust the green tick.
