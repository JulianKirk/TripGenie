# Student 1 Release 2 demonstration guide

Student 1 (Aaditya, `aadirai31`) owns Trip & Itinerary Management and the
group's Azure deployment. Use this guide to rehearse and record the Student 1
part of the group showcase video. It has a timed script, what to do on screen,
a pre-recording checklist, a command cheatsheet, troubleshooting notes and
short Q&A answers.

> **Status: provisional.** The "Plan my itinerary" panel comes from
> [PR #189](https://github.com/YourNightmareIsOver/TripGenie/pull/189), which is
> still a draft and not merged. The labels below were checked against that
> PR's published head `c7e326d` on 23 Oct 2026. Before recording, check them
> again against the commit you will actually show. This guide records no
> runtime result. Every field marked *Pending* must come from a real run.

## What the video needs from Student 1

The group video must be 10 minutes or less and must include all five
students. From the Release 2 brief, Student 1's part has to show:

- the Multi-Agent workflow (Planner → Worker → Reviewer → Human Review)
  working through the Student 1 frontend, with Student 1 CRUD still working
  alongside it;
- the frontend running locally, with the AI services on the host, and in the
  cloud;
- pre-commit security scanning, post-commit CI endpoint tests and the
  agentic-loop review modes;
- Student 1 explaining and defending their Release 2 contribution,
  including the cloud design.

**Suggested split (provisional; the group decides).** About 90 seconds for the
Student 1 feature on the local stack, then about 60 seconds for the shared
work Student 1 owns or contributed to: testing evidence, review output and
the cloud deployment. That budget is about 2:30 (90 + 60 seconds), and the
full script below rehearses at about 2:20–2:40, which leaves time for the
other four students. This is a planning suggestion, not an assessment rule.
If the group gives one person all the pre-commit, CI or review footage, cut
the matching beats below.

## Two recording gates

| Part | Can record when | Depends on |
| --- | --- | --- |
| **A. Local feature** (beats 1–6) | PR #189 is validated on the real host stack and you are recording from the commit you will submit | Ollama, AI-Mode, RAG, MCP and the Multi-Agent Server on the host; Compose up; a pre-run plan waiting for a decision |
| **B. Shared evidence and cloud** (beats 7–10) | The team has agreed the final deployment and that deployment has been checked | The final `cloud-deployment.yml` run; fresh pre-commit and CI evidence; agentic-loop outputs for that version |

The cloud report draft ([PR #186](https://github.com/YourNightmareIsOver/TripGenie/pull/186))
does not have to be merged before recording. The report, the video and the
release decision must all refer to the same chosen app version. The written
human release decision belongs to the user and team after review. A green CI
run or the `production` approval does not make that decision.

## Demo data

Use a disposable trip. Never show real personal data.

| Field | Value |
| --- | --- |
| Trip name | `Release 2 demo – Melbourne` |
| Destination | `Melbourne` |
| Start date / End date | `2026-11-12` / `2026-11-14` |
| Traveller count | `2` |
| Status | `Planned` |

- **Planner evidence.** Before the pre-run, attach at least one saved
  accommodation, transport option or activity to the trip. Use the owning
  teammate's frontend, and check its button labels in your precheck. The
  agents plan from what is saved on the trip, so an empty trip produces a thin
  plan.
- **On-camera itinerary item (create, then delete).** Title
  `Demo coffee stop`, Date `2026-11-13`, Start time `08:00`, End time `08:30`,
  Category `Meal`, Location `Degraves Street`.
- **Optional plan request.** "What should the plan focus on? (optional)":
  `Plan one relaxed day on 13 November around the saved items and keep the evening free.`
  The field takes up to 500 characters and can be left blank.
- **Cloud.** Create and delete a separate trip, `Cloud demo trip`, with
  Melbourne, 2026-11-12 to 2026-11-13. Cloud SQLite resets on every new
  revision, so anything you create there is temporary.

## Timed script

Times are cumulative. The narration is about 350 words. At 130–150 words a
minute it runs 2:20–2:40, so rehearse with a timer and use the cuts below if
needed. Each **Say** line is the exact narration. Square brackets mark a value
you must check or fill in before you say it.

### Part A: local feature (about 1:30)

**Beat 1, 0:00–0:08. Introduction.**
*Do:* Show the portal at `http://localhost:8080`, then open the Student 1 frontend (`http://localhost:8081`).

> **Say:** "I'm Aaditya, Student 1. I own Trip and Itinerary Management, and I
> also owned our Azure deployment. First, the local Release 2 stack."

**Beat 2, 0:08–0:22. Local architecture.**
*Do:* Show a terminal grid with one pane each for AI-Mode `:8006`, RAG `:8011`, MCP `:8012` and the Multi-Agent Server `:8013`, plus a pane showing `docker compose ... ps`.

> **Say:** "Docker Compose runs every frontend, backend and database. AI-Mode,
> RAG, MCP and the new Multi-Agent Server run outside Docker as host
> processes, one per terminal, and the backends reach them through host dot
> docker dot internal."

**Beat 3, 0:22–0:35. CRUD still works.**
*Do:* On the demo trip, click **Add itinerary item** and submit `Demo coffee stop`. The item appears under **View by day**. Click **Delete item**, then **Delete itinerary item**.

> **Say:** "Ordinary trip CRUD still works on its own. I add an itinerary item,
> it appears on its day, and I delete it again. My Release 1 RAG and MCP
> panels are still on this page."

**Beat 4, 0:35–1:05. The agents' work (from a pre-run).**
*Do:* Scroll to **Plan my itinerary**. The pre-run shows **Your plan is ready for a decision** with its Run ID. Open **Planner's plan**, then **Agent steps and tool evidence** (it should show `trip_get_context`). Point at **Deterministic checks** and the **Reviewer** verdict, issues and risks.

> **Say:** "This is Plan my itinerary. I started this run before recording,
> because a local model takes a minute or more; the run ID is on screen. The
> Planner chose what to look up, the Worker called the trip tools through MCP,
> the server's deterministic checks passed, and the Reviewer flagged risks.
> Nothing has been saved yet."

**Beat 5, 1:05–1:25. Human decision.**
*Do:* Under **Drafted items**, leave the items ticked and click **Approve all items**. The banner should read "All [N] approved item(s) are on your itinerary." Then scroll to the matching day under **View by day**.

> **Say:** "Now the human decision. I approve, and my backend, not the agent
> server, re-validates each item and saves it through the normal itinerary
> path. Correct, partial and reject work the same way; reject saves nothing.
> This runtime review is separate from our development agentic loop and from
> the GitHub production approval."

**Beat 6, 1:25–1:32. Terminal view of the same run.**
*Do:* In a terminal at `ai-services\multi-agent-server` (the Multi-Agent Server's environment), run `python -m multi_agent_service show <run_id>`, or show that run's export, and highlight the human decision.

> **Say:** "The same run from the terminal: its history and audit log record
> my decision."

### Part B: shared evidence and cloud (about 1:00)

**Beat 7, 1:32–1:44. Pre-commit security scan.**
*Do:* Show the terminal output of a fresh `security` hook run on the release commit: three `passed` lines and `Security gate: passed`.

> **Say:** "Our local pre-commit security gate runs Ruff security rules,
> detect-secrets and pip-audit. This is a fresh scan of the release commit,
> and [all three checks passed]."

**Beat 8, 1:44–1:56. Post-commit endpoint tests.**
*Do:* Open the final Student 1 CI run, show the **Endpoint test summary** table, then the `student-1-endpoint-test-evidence` artifact.

> **Say:** "After a push, student-1-ci tests two endpoint functions, creating a
> trip and adding an itinerary item, against the real Compose stack. [Seven]
> tests passed, and the results are uploaded as an artifact."

**Beat 9, 1:56–2:06. Agentic-loop reviews.**
*Do:* Show the Student 1 Multi-Agent Review output: the run under review, the checks table and the human decision. Then show the Student 1 rows of the Testing Review.

> **Say:** "Our shared agentic loop then reviewed my workflow run and my
> testing evidence. Its deterministic checks decide pass or fail; the Claude
> comments are advisory."

**Beat 10, 2:06–2:30. Cloud.**
*Do:* Open the Student 1 cloud frontend, already warmed up, and show the HTTPS padlock. Click **Create trip**, save `Cloud demo trip`, then **Delete trip** and confirm. Flash the final Cloud Deployment run, which shows the `production` approval.

> **Say:** "Finally, the same frontend on Azure Container Apps, over HTTPS. I
> create a trip and delete it. GitHub Actions deployed this release with
> OIDC, no stored passwords, after a required production approval. The AI
> services stay on our machines, so the AI panels are off here. Back to
> [next presenter]."

### Cuts and extra footage

- **If a rehearsal runs over the slot the group agrees:** drop beat 6 and
  shorten beat 3 to "CRUD still works". If the group's shared section already
  covers the pre-commit, CI and review footage, drop beats 7–9 and keep beat
  10 plus one sentence on your own evidence. These cuts are provisional; time
  the shortened take again rather than assuming how much it saves.
- **Optional backup footage** (record separately; use only if time allows or
  someone asks):
  - **Reject:** a second real pre-run on the same trip, then **Reject plan**.
    The banner should read "Nothing was saved: you rejected this plan."
  - **Correct:** edit one drafted item under **Correct item [n]**, then click
    **Save corrections**.
  - **Terminal run:** a terminal-only run through the shared server, from
    `ai-services\multi-agent-server` in the server's environment:
    `python -m multi_agent_service run --feature student-1 --trip-id <trip_id> --task "..." --no-review`.
    It uses the server's generic answer schema, not the Student 1 backend's
    planner prompt, so present it as the shared server's terminal path.
- Show each decision on its own run. A run takes exactly one decision.
  Clicking **Reject plan** on a run you already approved returns
  `MULTI_AGENT_ALREADY_DECIDED` and does not demonstrate rejection.

## Rules for honest footage

- **Pre-runs.** A pre-run is a genuine run started before recording and left
  at `awaiting_human`. Say it is a pre-run (beat 4 does). Never fake, mock,
  edit or replay model output, and do not cut footage to suggest that a
  pre-run was generated live.
- **Same version everywhere.** The run IDs, audit export, review outputs, CI
  run and cloud deployment must all belong to the same app version. Note the
  SHA in the evidence record below.
- **Nothing sensitive on screen.** Hide tokens, `ANTHROPIC_API_KEY`, Azure
  subscription or tenant IDs, `.env` contents, personal emails and browser
  autofill. Close unrelated tabs and notifications.
- **Only claim what was checked.** If the agentic loop's Claude sections
  print "unavailable", show the deterministic checks and say that the advisory
  review was unavailable. Never call a review "passed" when the model did not
  run.

## Ready-to-record checklist

Tick items only after you have checked them on the version you will submit.

### Version and stack (Part A)

- [ ] *Pending:* PR #189 merged, or its final head validated, and the head SHA and branch written in the evidence record.
- [ ] The Multi-Agent Server comes from the same `main` as the Student 1
      code. PR #189 needs the server's `feature_instructions` field (from
      #191). Restart the host processes after pulling.
- [ ] Ollama models pulled, and AI-Mode, RAG (index built), MCP and the
      Multi-Agent Server started in the order given in the
      [local host services runbook](../release-1/local-host-services-runbook.md)
      (PR #189 adds the Student 1 steps). Every `/health` or `/ready` check in
      its "Verify" section answers.
- [ ] Compose is up, and `docker compose ... ps` shows the services healthy.
- [ ] The demo trip exists and has at least one item saved from a teammate's service.
- [ ] Functional precheck in the browser:
  - [ ] create, edit and delete a trip and an itinerary item;
  - [ ] get one RAG answer with citations;
  - [ ] get one MCP tool result;
  - [ ] start one **Plan my itinerary** run.
- [ ] *Pending:* all four decisions tested on separate real runs:
  - [ ] approve all;
  - [ ] save selected (partial);
  - [ ] save corrections;
  - [ ] reject, with nothing saved.

  Also check that repeating a decision shows "Already on the itinerary" and
  that a conflicting decision is refused.
- [ ] One fresh **pre-run** waiting at "Your plan is ready for a decision",
      with no problem badges on the items you will approve. Note its Run ID
      and page URL.
- [ ] Optional: a second pre-run kept for the reject footage.
- [ ] *Pending:* the audit export of the recorded run saved, and the
      terminal pane ready with `show <run_id>`.

### Evidence (Part B)

- [ ] *Pending:* a fresh `pre-commit run security --all-files` on the
      release commit, with its date and SHA noted. The hook writes JSON to the
      path printed by `git rev-parse --git-path security-reports/latest.json`
      (view it with `Get-Content (git rev-parse --git-path security-reports/latest.json)`).
      It does not update the [security report](student-1-pre-commit-security-report.md).
- [ ] *Pending:* the Student 1 CI run for the release SHA is green, its
      **Endpoint test summary** is open, and the test count is filled into
      beat 8.
- [ ] *Pending:* Student 1's Multi-Agent Review and Testing Review outputs
      exist for this version, and the team has agreed where they are stored
      (see the cheatsheet).
  - [ ] Both Claude agent sections in each output contain real findings,
        with the model names recorded. A section that says "unavailable"
        means the agentic review did not happen.
  - [ ] Green deterministic checks alone do not satisfy the agentic review
        requirement. If a model section was unavailable, leave this item
        *Pending*, rerun with credentials, and do not show or describe that
        output as a completed review.
  - [ ] The human decision recorded in each output is your own, made after
        reading the findings.
- [ ] *Pending:* the team has agreed the final cloud deployment, and its run
      URL and SHA are recorded.
- [ ] On the final cloud deployment:
  - [ ] the Student 1 page shows no AI panels;
  - [ ] CRUD works;
  - [ ] the URL is HTTPS.

  If the AI panels are still visible, that deployment predates #190 or #189;
  do not say they are off.

### Recording setup

- [ ] Browser windows ready:
  - [ ] the portal;
  - [ ] the Student 1 trip page;
  - [ ] the final CI run;
  - [ ] the review outputs;
  - [ ] the Cloud Deployment run;
  - [ ] the cloud frontend.
- [ ] Use zoom of at least 125% and close unrelated tabs.
- [ ] Terminal grid with a readable font, history cleared of secrets, and
      no `env` or `.env` output.
- [ ] Cloud frontends warmed up 2–3 minutes before recording. They scale to
      zero; a cold portal load took 17.6 s on 21 Oct.
- [ ] Rehearsed once with a timer, and the hand-off line agreed.

### Afterwards

- [ ] Delete the disposable cloud trip, if the take did not already delete it.
- [ ] Remove or keep the local demo trip on purpose. `docker compose down -v`
      deletes every feature's data, so do not use it casually.
- [ ] Save the published video timestamps in the evidence record.

## Evidence record (fill in; do not guess)

| Field | Value |
| --- | --- |
| App version (SHA) used for local recording | *Pending* |
| PR #189 merge SHA, or validated head | *Pending* |
| Recorded run ID / correlation ID | *Pending* |
| Optional reject run ID | *Pending* |
| Audit export location | *Pending* |
| Pre-commit scan: date, SHA, result | *Pending* |
| Student 1 CI run URL and test count | *Pending* |
| Multi-Agent Review output, run ID it reviewed, and whether both model sections ran | *Pending* |
| Testing Review output, and whether both model sections ran | *Pending* |
| Final Cloud Deployment run URL and SHA | *Pending (team decision)* |
| Cloud Deployment Review output | *Pending* |
| Cost figure and date range quoted | *Pending* |
| Written human release decision | *Pending (user/team)* |
| Video URL and Student 1 timestamps | *Pending* |

Context for the cloud fields: at 10:49 AEDT on 23 Oct, the latest successful
deployment was
[run 39870145500](https://github.com/YourNightmareIsOver/TripGenie/actions/runs/39870145500)
at `9f51e72`. It predates #190 and #189. The 21 Oct figures in PR #186
(deployment of `188951a`, screenshots, cost) are dated evidence. Do not
present either as the final release.

## Command and evidence cheatsheet

Commands are for Windows PowerShell. The **Run from** column gives the working
directory relative to the repository root; `Set-Location` there first. Startup
commands are in the [local host services runbook](../release-1/local-host-services-runbook.md)
and are not repeated here. Call `curl.exe`, not the `curl` alias.

Python environments:

- **Multi-Agent Server CLI** (`ai-services\multi-agent-server`): use the
  environment where you ran `python -m pip install -e ".[dev]"` for the
  runbook, which is the same one serving `:8013`. `list`, `show` and `export`
  query the running server at `http://127.0.0.1:8013` (override with `--url`),
  so the server must be up. A relative `--output` path is resolved from this
  directory; do not leave stray exports in the repository unless the team
  commits them as evidence.
- **Agentic loop** (`ai-services\agentic-loop`): use an environment where you
  ran `python -m pip install -r requirements.txt`. The Claude credentials must
  already be in the environment, and the testing and cloud modes need
  `gh auth login` first.
- `$env:` variables last for the rest of that PowerShell session. Clear them
  with `Remove-Item Env:RUN_ID` (or `Env:CLOUD_RUN_ID`, `Env:CLOUD_URL`)
  before reviewing a different run.

| Purpose | Run from | Command or location |
| --- | --- | --- |
| Compose status | repository root | `docker compose --env-file shared\configuration\.env.example ps` |
| Host readiness | any | the runbook's "Verify" section (`:8006`, `:8011`, `:8012`, `:8013`, `:18001`) |
| Student 1 backend multi-agent API | any | the curl steps in [PR #189's runbook update](https://github.com/YourNightmareIsOver/TripGenie/pull/189/files): `POST`/`GET /api/trips/{trip_id}/multi-agent-plan[/{run_id}]` and `POST .../review` |
| Reopen a pre-run in the browser | browser | `http://localhost:8081/trips/<trip_id>/multi-agent-plan/<run_id>` (the page the panel's "Refresh status" link opens) |
| Runs for Student 1 | `ai-services\multi-agent-server` | `python -m multi_agent_service list --feature student-1` |
| One run's details | `ai-services\multi-agent-server` | `python -m multi_agent_service show <run_id>` |
| History and audit export | `ai-services\multi-agent-server` | `python -m multi_agent_service export <run_id> --format markdown --output <file>.md` (or `--format json --output <file>.json`) |
| Pre-commit scan | repository root | `pre-commit run security --all-files --verbose` |
| Latest scan JSON | repository root | `Get-Content (git rev-parse --git-path security-reports/latest.json)` |
| Student 1 CI evidence | browser | Actions → **Student 1 CI** → **Validate Student 1 Compose Readiness** → **Endpoint test summary**; artifact `student-1-endpoint-test-evidence` |
| Multi-Agent Review | `ai-services\agentic-loop` | `$env:RUN_ID = '<run_id>'; python agentic_loop.py --mode multi-agent` |
| Testing Review | `ai-services\agentic-loop` | `python agentic_loop.py --mode testing` |
| Cloud Deployment Review (interactive) | `ai-services\agentic-loop` | `$env:CLOUD_RUN_ID = '<deploy_run_id>'; $env:CLOUD_URL = '<final_student_1_frontend_url>'; python agentic_loop.py --mode cloud` (`CLOUD_URL` is optional) |
| Cloud frontends | browser | `https://student-1-frontend.lemonrock-5a94d8cd.australiaeast.azurecontainerapps.io` and `https://shared-ui.lemonrock-5a94d8cd.australiaeast.azurecontainerapps.io` (listed by run 39870145500; re-check on the final run) |

Notes on the agentic loop
([README](../../../ai-services/agentic-loop/README.md)):

- **Pin the run.** Without `RUN_ID`, the multi-agent mode picks the newest
  decided run on the server, which could be a teammate's. Set `RUN_ID` to
  the Student 1 run.
- **Shared output files.** The `multi-agent`, `testing` and `cloud` modes
  overwrite the shared committed files
  `docs/reports/release-2/agentic-loop/<mode>-review.md` and `.json`. The
  current `multi-agent-review.md` reviews a Student 3 run. Agree with the team
  where Student 1's output goes before committing, for example as a
  separately named copy. Do not overwrite a teammate's evidence. A timestamped
  copy is also written to the git-ignored `reports/` folder.
- **Credentials and decisions.** The two review agents call Claude using
  credentials from the environment, so never print them. Each run is a paid
  model call. `--ci` skips the human decision prompt; for the cloud mode, a
  non-interactive run records the release decision as `PENDING`.

## Troubleshooting

| Symptom | What to do |
| --- | --- |
| No **Plan my itinerary** panel | `STUDENT1_BACKEND_MULTI_AGENT_ENABLED` is `false`, or the stack predates #189. Locally it defaults to `true`; in the cloud it is `false` by design. |
| Panel error: unavailable or timeout (`DEPENDENCY_UNAVAILABLE` / `DEPENDENCY_TIMEOUT`) | The Multi-Agent Server on `:8013` is stopped or unreachable from the container. Run the runbook's in-container `host.docker.internal` check. |
| Busy (`RUN_LIMIT_REACHED`) | Teammates share one server. Wait for their runs to finish; do not start duplicates. |
| Every run fails to start, even though `:8013/ready` answers | The host server may be older than #191, which rejects the `feature_instructions` field. Pull `main` and restart it. |
| "The agents could not finish this plan" | The run failed and nothing was saved. Read the error code and click **Plan again**. Do not record the failed run as success. |
| **Approve all items** refused, naming an item | That item has a "Cannot be saved as drafted" problem. Untick it and use **Save selected items**, or fix it under **Correct item [n]** and use **Save corrections**. |
| "Only [k] of [n] approved items are on your itinerary" | Click **Retry saving the missing items**. Only the missing items are written, and saved items are never duplicated. |
| `MULTI_AGENT_ALREADY_DECIDED` | That run already has a different decision. Use a new run. |
| Stuck in "planning", "working" or "reviewing" | A cold 8b model is slow. Check the AI-Mode terminal, and use the **Refresh status** link if JavaScript is off. |
| The cloud page loads slowly | It is a cold start from zero replicas. Warm it up before recording. |
| A trip created in the cloud has disappeared | A new revision or restart reset the ephemeral SQLite. Expected. |
| A review section prints "unavailable" | No Claude credentials, or the model call failed. The checks still set the exit code, but that output is not agentic review evidence. Fix the credentials and rerun before you rely on it, and say so honestly if you show it. |

## Q&A cards

**Why does my backend, not the agent server, write itinerary items?**
The Multi-Agent Server never writes feature data. Its Worker is limited to
the read-only tools `trip_get_context` and `trips_list_itinerary_items`, and a
`no_writes` check enforces that. After the human decides, the Student 1
backend re-validates each approved item and saves it through the existing
`create_itinerary_item` path, with the same rules as manual CRUD.

**How are drafts grounded and validated?**
The server runs deterministic checks: `output_schema`, `allowed_tools`,
`tool_evidence`, `no_writes` and `grounding`. The grounding check requires
each `source_id` to come from a Student 1 tool result. My backend then
re-checks each draft:
- **Blocking problems:** dates outside the trip, invalid times, repeats of
  existing items, and domain-rule failures.
- **Warnings:** clashes, and sources not saved on the trip.

A model verdict is never the only gate.

**What about duplicates, retries and partial failure?**
- **No duplicates:** item IDs are deterministic (`item_{run_id}_{index}`).
- **Same decision repeated:** only missing items are written; the rest are
  reported as `already_saved`.
- **Different decision:** returns `409 MULTI_AGENT_ALREADY_DECIDED`.
- **Partial failure:** each item reports `saved`, `already_saved` or
  `failed`, and the outcome never claims everything was saved when it was
  not.
- **Reject** writes nothing.
- **Write tools:** the server never repeats an attempt that ran one.

**How is the Multi-Agent Server different from the agentic loop?**
The server (`:8013`) is part of the running app: Planner, Worker, Reviewer,
then a traveller's decision. The agentic loop (`agentic_loop.py`) is a local
development harness that validates evidence. Its deterministic checks set
the exit code, and its Claude comments are advisory. The GitHub `production`
approval authorises a deployment. These are three separate human checkpoints.

**Where is the container boundary?**
Compose runs the shared service and each student's frontend, backend and
database. Ollama, AI-Mode, RAG, MCP, the Multi-Agent Server and the loop run
on the host, and backends reach them at `host.docker.internal`. Student 1 CI
fails if AI-Mode, MCP, RAG, Ollama or the agentic loop appears as a Compose
service, and #189 adds the Multi-Agent Server to that guard.

**Why is AI off in the cloud, and does the app still work?**
The brief requires AI off in the baseline. No AI service is deployed, and
[`.env.cloud`](../../../shared/configuration/.env.cloud) switches off the
Student 1 RAG and MCP flags and leaves the AI-Mode URL blank. With #189, it
also switches off the multi-agent flag. #190 hides panels that are switched
off. Human CRUD is unaffected. Only claim this for a deployment that
contains these changes. No optional cloud-AI bonus is claimed.

**How do I know which code produced this evidence?**
- **Runtime evidence:** the run ID and correlation ID identify a run, and
  `/health` and `/ready` show that a process serves and that its dependencies
  are reachable. None of these says which code is running.
- **Code version:** deployed images are tagged with the commit SHA, and each
  CI or deploy run records its head SHA.

**OIDC versus secrets?**
GitHub Actions exchanges a short-lived OIDC token for a managed identity's
access, so the repository stores identifiers, not passwords. The registry's
admin user is off. The apps pull images with a separate
`tripgenie-acr-pull` identity that holds only AcrPull. Deployment runs only
from `main`, behind a required `production` reviewer.

**How does HTTPS work behind Container Apps?**
Ingress terminates TLS and forwards the request to the app over plain HTTP.
In the cloud, `TRIPGENIE_FORWARDED_ALLOW_IPS` lets uvicorn trust
`X-Forwarded-Proto`, so the pages generate `https://` links (#187). Locally,
only loopback is trusted. Six frontends have external HTTPS ingress; the
twelve backends and databases are internal TCP only.

**What are the trade-offs?**
- **Data:** each database is one replica of SQLite on the container
  filesystem, and it resets on every restart or new revision. There is no
  Azure Files share.
- **Cold starts:** frontends scale to zero to save cost, so the first load is
  slow.
- **Observability:** app logs are not routed to Log Analytics.
- **Cost:** the quoted figure is dated and partial.

This setup is fine for a course baseline, but it does not give production
durability.

## Related documents

- [Local host services runbook](../release-1/local-host-services-runbook.md)
- [Multi-Agent Server README](../../../ai-services/multi-agent-server/README.md)
  and [contract](../../architecture/release-2-multi-agent-contract.md)
- [Agentic loop README](../../../ai-services/agentic-loop/README.md)
- [Student 1 pre-commit security report](student-1-pre-commit-security-report.md)
- [Student 1 post-commit testing report](student-1-post-commit-testing-report.md)
- [Azure deployment guide](../../../scripts/deploy/azure/README.md)
- [PR #189](https://github.com/YourNightmareIsOver/TripGenie/pull/189)
  (Student 1 multi-agent) and
  [PR #186](https://github.com/YourNightmareIsOver/TripGenie/pull/186)
  (cloud report draft), both unmerged when this guide was written
- [Issue #177](https://github.com/YourNightmareIsOver/TripGenie/issues/177)
  and [issue #176](https://github.com/YourNightmareIsOver/TripGenie/issues/176)
