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

Students 4 and 5 have no backend yet -- their images serve a static directory,
so their files check only that the container answers. Replace those with real
endpoint checks when the backends land.

## Run it

```bash
pip install -r requirements.txt
docker compose -f ../../docker-compose.yml -f docker-compose.agentic.yml \
  up -d --build student-1-backend
SERVICE_URL=http://127.0.0.1:8001 CHECKS_FILE=checks/student-1.json python agentic_loop.py
```

The overlay publishes student 3's backend, which is internal-only in the main
compose file; every other service already publishes its port.

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

`.github/workflows/agentic-ci.yml` runs on push and pull request, one job per
service. Each job is a post step: before doing anything it polls that service's
own build-and-validate workflow for the same commit, and stops if it failed. If
that workflow never runs -- its path filters skipped the commit -- the loop
carries on after a two minute grace period.

The gate lives in a step rather than in a `workflow_run` trigger because
`workflow_run` only fires from the default branch's copy of a workflow file, so
it does nothing on a feature branch.

`services.json` is the map from service name to compose service, port, and
health path -- the workflow builds its matrix from it, so a new service is a new
entry there plus a `checks/` file.

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
