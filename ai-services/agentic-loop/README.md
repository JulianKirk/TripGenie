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

Student 4's loop starts its database, backend, and frontend with `--no-deps`.
Its shared-location, itinerary, and AI integrations are optional for the
read-only checks, so `/health` is expected to be degraded while `/ready` proves
the owned database path is available.

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

The two agents call Claude. Credentials come from the environment the way the
`anthropic` SDK resolves them -- `ANTHROPIC_API_KEY`, or an `ant auth login`
profile locally. The implementation agent defaults to `claude-sonnet-5` and the
reviewer to `claude-opus-5`; the reviewer checks the recommendation, so it is
the more capable of the two. Override either with `IMPLEMENTATION_MODEL` /
`REVIEW_MODEL`. With no credentials the agent sections print "unavailable" and
the run still passes or fails on the checks, so CI works either way (add
`ANTHROPIC_API_KEY` to the repository secrets to turn them on).

## In CI

`.github/workflows/agentic-ci.yml` runs on push and pull request as three jobs:

- **Loop unit tests** -- `pytest` on the loop itself. Always runs, starts no
  containers, and is the reason a change to `agentic_loop.py` still gets tested
  when every service below is skipped. One registry-contract test uses
  `docker compose config`, which is available on the GitHub runner.
- **Pick services** -- the gate. For each service it polls that service's own
  build-and-validate workflow for this commit and decides whether the loop runs.
- **One job per chosen service** -- the loop.

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

On a pull request the workflow posts that same report as a comment -- one per
service, edited in place on later pushes rather than appended, so a busy pull
request does not fill with tables. It posts whether the loop passed or failed,
and says nothing at all when the commit is not on an open pull request.

Findings are advisory. Only the deterministic checks set the exit code, so a
broken or unauthenticated Claude call cannot fail the build -- and equally,
cannot block it. Read the summary, don't just trust the green tick.
