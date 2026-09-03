# Student 1 manual evidence capture

Status: **pending manual capture**

This directory intentionally contains instructions only. No local Compose run,
browser session, live Ollama response, Agentic Loop transcript, video, or
attendance record was available to commit when this evidence pack was prepared.

## 1. Capture rules

- Use a real dated run from the same commit recorded in the evidence notes.
- Record the OS, Docker version, Compose version, Ollama version, selected
  approved model, and commit SHA.
- Keep expected, actual, and pass/fail separate.
- Preserve failures and degraded states; do not rewrite output into success.
- Redact tokens, usernames, machine names, and unrelated personal information.
- Do not include local absolute paths.
- Do not commit `.env` files, secrets, generated SQLite files, container
  volumes, raw model caches, or unbounded logs.
- Prefer text for command output and PNG/JPEG only where a browser view is
  required.

Use filenames beginning with the capture date:

```text
YYYY-MM-DD-environment.md
YYYY-MM-DD-compose-ps.txt
YYYY-MM-DD-compose-logs.txt
YYYY-MM-DD-health.txt
YYYY-MM-DD-seed-counts.txt
YYYY-MM-DD-crud-create.png
YYYY-MM-DD-crud-read.png
YYYY-MM-DD-crud-update.png
YYYY-MM-DD-crud-delete.png
YYYY-MM-DD-ai-request.png
YYYY-MM-DD-ai-response.txt
YYYY-MM-DD-agentic-loop.txt
YYYY-MM-DD-test-results.md
```

## 2. Environment and Compose capture

From the repository root, record versions and the exact commit:

```bash
git rev-parse HEAD
docker --version
docker compose version
ollama --version
ollama list
```

Start the host-managed Ollama service using the team's operating-system
procedure. Confirm that the model configured in
`shared/configuration/.env.example` is installed, then run:

```bash
docker compose --env-file shared/configuration/.env.example up --build -d
docker compose --env-file shared/configuration/.env.example ps
docker compose --env-file shared/configuration/.env.example logs --no-color --tail 200 student-1-frontend student-1-backend student-1-database ai-mode
```

Save actual output. A merged `docker-compose.yml` or successful image build is
not a substitute for this capture.

## 3. Health, seed, and CRUD capture

Record the shared portal and Student 1 frontend responses:

```bash
curl -i http://localhost:8080/
curl -i http://localhost:8081/health
curl -i http://localhost:8081/ready
```

Use the browser at `http://localhost:8080` to reach Student 1. Capture one
disposable record through:

1. create a trip;
2. read its list and detail views;
3. update a visible field;
4. create, read, and update an itinerary item;
5. delete the disposable itinerary item; and
6. delete the disposable trip only if that will not remove evidence needed by
   the group demonstration.

Record actual seeded Trip and Itinerary Item counts through the running APIs or
database API. Include representative record identifiers, but do not copy the
SQLite file into this directory.

## 4. Live AI-Mode capture

From the Student 1 trip page, make one real request using the installed approved
model. Capture:

- requested trip/date and bounded goal;
- selected model;
- prompt asset version;
- run ID and correlation ID;
- attempt count;
- returned draft or real error;
- proof that the result was not automatically persisted; and
- the human decision to accept, edit, or reject the draft.

If Ollama is unavailable or the output is poor, record that outcome and the
mitigation. Do not use the closed PR #35 fake provider or any synthetic output
as live Ollama evidence.

## 5. Assessed loop and pre/post testing

Use the real Student 1 environment and the checked-in assets under
[`ai-services/agentic-loop`](../../../../../ai-services/agentic-loop). The
record must include:

1. **Plan** — bounded goal, pass condition, and stop condition.
2. **Act / Observe** — actual deterministic command, browser, API, database,
   and timing observations.
3. **Implementation output** — prompt asset/model and verbatim bounded result.
4. **Review output** — prompt asset/model and evidence-based risk/correction/
   retest result.
5. **Human decision** — accept, partially accept, or reject, with rationale.
6. **Adapt** — one bounded change.
7. **Rerun** — the same relevant checks with actual before/after results.

The current shared tool can be run locally without `--ci` so the human-review
decision is not skipped. If agent credentials are unavailable, its output says
the agents are unavailable; that is not a qualifying implementation/review
record and must remain documented as a limitation.

## 6. Final evidence note

For every captured item, add a short entry to
[the evidence register](../../student-1-evidence-register.md) containing:

- date and timezone;
- commit SHA;
- relative artefact path;
- expected result;
- actual result;
- pass/fail;
- recorder/reviewer; and
- any limitation or follow-up.

After capture, stop and remove only the containers/volumes created for this
demonstration using the team's agreed data-retention decision:

```bash
docker compose --env-file shared/configuration/.env.example down --remove-orphans
```
