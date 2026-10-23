# Local host services and cloud demonstration runbook

Release 1 runs AI-Mode, RAG, MCP, Ollama, and the agentic loop as host
processes; Release 2 adds the Multi-Agent Server. Docker Compose runs only the shared reference service and the
feature frontends, backends, and databases. Backends reach the host through
`host.docker.internal`.

For recording, use the [local planner walkthrough](#student-1-planner-prompts-and-recording-walkthrough)
and the separate [Azure cloud walkthrough](#student-1-cloud-demonstration-walkthrough).
The latter demonstrates the deployed application, security controls and
deployment evidence; it does not run the host-only AI workflow in Azure.

| Host process | Port | Container URL | Host URL |
| --- | --- | --- | --- |
| Ollama | 11434 | not used | `http://127.0.0.1:11434` |
| AI-Mode | 8006 | `http://host.docker.internal:8006` | `http://127.0.0.1:8006` |
| RAG | 8011 | `http://host.docker.internal:8011` | `http://127.0.0.1:8011` |
| MCP | 8012 | `http://host.docker.internal:8012/mcp` | `http://127.0.0.1:8012/mcp` |
| Multi-Agent (Release 2) | 8013 | `http://host.docker.internal:8013` | `http://127.0.0.1:8013` |

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
timeout allows a cold model load but does not guarantee that an 8b model fits
the host GPU. Check `ollama ps` and measure a complete workflow before recording.

### Student 1 profile for a 4 GB GPU (Windows PowerShell)

An 8b model can spill heavily into CPU memory on this hardware. Student 1's
failed runs completed their MCP reads quickly but timed out in generation;
raising the timeout did not make that configuration suitable for a demo.
Use a smaller tool-capable model rather than weakening the workflow checks.
This is a local profile, not a change to shared defaults or cloud settings.

Pull the model once (approximately 1.9 GB); keep the embedding model from step 1
for RAG. In the AI-Mode terminal, from the repository root and using its Python
environment:

```powershell
ollama pull qwen2.5:3b
Set-Location ai-services\ai-mode
$env:AI_MODE_DEFAULT_MODEL = 'qwen2.5:3b'
$env:AI_MODE_ALLOWED_MODELS = 'qwen2.5:0.5b,qwen2.5:3b,llama3.1:8b'
$env:AI_MODE_CONTEXT_TOKENS = '12288'
$env:AI_MODE_TIMEOUT_SECONDS = '90'
$env:AI_MODE_AGENT_TIMEOUT_SECONDS = '180'
$env:AI_MODE_MCP_URL = 'http://127.0.0.1:8012/mcp'
python -m uvicorn ai_mode_service.app:app --host 127.0.0.1 --port 8006
```

In the separate Multi-Agent terminal, from the repository root and using the
Multi-Agent Server's Python environment:

```powershell
Set-Location ai-services\multi-agent-server
$env:MULTI_AGENT_MODEL = 'qwen2.5:3b'
python -m multi_agent_service serve
```

Keep the normal Planner, Worker, Reviewer and total-run deadlines. The model
allow-list must include the selected model; changing only `MULTI_AGENT_MODEL`
is insufficient. Host services do not load the Compose environment file.
Model output remains advisory: test your actual trip and request before the
take, inspect grounding and dates, and never treat a timeout as a successful run.
The [Student 1 runtime evidence](../release-2/student-1-multi-agent-runtime-evidence.md)
records four real Compose/browser decisions in 25-46 seconds, the exact
general-note request, and observed failures on other requests. This profile
improves practical runtime; it does not guarantee model accuracy.

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

Set `MCP_HOST` for a non-loopback binding. AI-Mode `/generate` (feature MCP
assistants) needs MCP running. RAG answers use `/generate-plain` and do not.

## 4b. Multi-Agent Server (terminal 4, Release 2)

```bash
cd ai-services/multi-agent-server
python -m pip install -e ".[dev]"
python -m multi_agent_service serve
```

Its Planner, Worker, and Reviewer run on AI-Mode, and the Worker uses MCP
through AI-Mode `/generate`, so start it after both. Run history is kept in
`ai-services/multi-agent-server/data/runs.sqlite3` (git-ignored). See
`ai-services/multi-agent-server/README.md` for the terminal workflow and the
feature-backend integration kit.

## 5. Docker Compose

```bash
docker compose --env-file shared/configuration/.env.example config --quiet
docker compose --env-file shared/configuration/.env.example up --build -d
```

Containers start and pass their health checks whether or not the host services
are running; an unreachable host service disables only the AI, RAG, or MCP
feature. To turn Student 1's RAG or MCP client off explicitly, set
`STUDENT1_BACKEND_RAG_ENABLED=false` or `STUDENT1_BACKEND_MCP_ENABLED=false`;
Student 1's Release 2 "Plan my itinerary" is `STUDENT1_BACKEND_MULTI_AGENT_ENABLED`
(Compose default `true`; `false` in Student 1 CI and `.env.cloud`, where it
answers `503 MULTI_AGENT_DISABLED` and the trip page leaves the panel out; it
needs the Multi-Agent Server from main after #191, which accepts
`feature_instructions`)
(Student 5 has matching `STUDENT5_BACKEND_*` flags, and Student 3 has
`STUDENT3_BACKEND_MCP_ENABLED` and `STUDENT3_BACKEND_RAG_ENABLED`). Student 2
turns its RAG guide off with an empty `STUDENT2_BACKEND_RAG_URL=` and its MCP
assistant with an empty `AI_MODE_URL`, because AI-Mode runs that tool loop.

## 6. Verify

```bash
curl http://127.0.0.1:8006/health
curl http://127.0.0.1:8006/ready
curl http://127.0.0.1:8011/health
curl http://127.0.0.1:8011/ready
curl http://127.0.0.1:8012/health
curl http://127.0.0.1:8013/ready
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

Run one Planner → Worker → Reviewer → human review workflow from the
terminal (from `ai-services/multi-agent-server`):

```bash
python -m multi_agent_service run --feature student-3 \
  --task "What is the cheapest way to get from Melbourne to Sydney for two travellers?"
python -m multi_agent_service export <run_id> --format markdown
```

Student 1's "Plan my itinerary" through its own backend (Compose up, the
Multi-Agent Server running; replace the trip id with one of yours). The start
returns `202` at once; poll until `status` is `awaiting_human`, then decide:

```bash
trip=http://127.0.0.1:18001/api/trips/trip_2026_melbourne_food_trail
curl -s -X POST -H 'Content-Type: application/json' -d '{}' "$trip/multi-agent-plan"
curl -s "$trip/multi-agent-plan/<run_id>"          # repeat until awaiting_human
curl -s -X POST -H 'Content-Type: application/json' \
  -d '{"decision":"partial","accepted_items":[0]}' "$trip/multi-agent-plan/<run_id>/review"
curl -s "$trip/itinerary-items" | grep "item_<run_id>_"   # what was saved
```

The same run is visible from `ai-services/multi-agent-server` with
`python -m multi_agent_service export <run_id> --format markdown`. In the
browser, open the trip at `http://localhost:8081`, use **Plan my itinerary**,
and try each of approve, save corrections, save selected and reject on
separate runs. Record only what a real run produced; Release 2 evidence goes
under `docs/reports/release-2/`.

Then open the portal at `http://localhost:8080` and exercise each feature's
AI, MCP, and RAG flows.

## Student 1 planner prompts and recording walkthrough

Use the **What should the plan focus on? (optional)** field under **Plan my
itinerary**. You enter one request; the server runs Planner, Worker and
Reviewer automatically. Approve, correct, partial and reject are human
decisions made with the buttons afterwards, not four different agent prompts.

Use the small-GPU profile above. These instructions match the
[four completed real-model runs](../release-2/student-1-multi-agent-runtime-evidence.md);
they do not promise that a new model response will be identical.

### Prepare the trip

For the isolated recording stack, open `http://127.0.0.1:18353`; its portal is
`http://127.0.0.1:18380`. The standard runbook stack uses `:8081` and `:8080`.
Keep Docker Desktop, Ollama and the host AI services running.

Create a fresh trip for each walkthrough, named `Planner demo - approve`,
`Planner demo - correct`, `Planner demo - partial` or `Planner demo - reject`:

| Field | Value |
| --- | --- |
| Destination | `Singapore` |
| Start / end date | `2026-11-12` / `2026-11-14` |
| Travellers / status | `1` / `Planned` |
| Existing itinerary item | `Saved dinner`, `2026-11-14`, `18:00`-`19:00`, category `Meal` |
| Dinner description | `An existing dinner on the last trip day.` |

Leave the first two days empty. Separate trips prevent previously approved
notes from changing the next run's evidence or triggering duplicate warnings.
Do not create all four runs on one trip and then approve them in sequence.

**Already-prepared take:** the isolated stack has `Release 2 demo - Singapore`,
with run `magent_ec8c2096913b` left at human review when it was prepared on
23 October. Open
`http://127.0.0.1:18353/trips/trip_31f1f9e5228e48d2/multi-agent-plan/magent_ec8c2096913b`.
If it still says **Your plan is ready for a decision**, you can use it for the
approve footage without generating another plan. If you have already decided
it, create a fresh trip/run instead; it cannot be reset to undecided.

### Prompt to paste for each walkthrough

```text
Draft exactly two general travel-preparation notes: check travel documents on 2026-11-12, and pack a day bag on 2026-11-13. These are new general notes, not bookings or saved activities. Use category note, null times, and no invented venue.
```

Click **Plan my itinerary** once and wait for **Your plan is ready for a
decision**. The measured runs took 25-46 seconds; allow for a cold model and
do not submit duplicates while it is working.

Before choosing a decision, show **Planner's plan**, **Agent steps and tool
evidence**, **Deterministic checks**, and the **Reviewer** verdict. Confirm a
successful `trip_get_context` call, two drafted notes on the requested dates,
no invented venue or booking, and no blocking item problems. The original
dinner should still be the only saved item.

### Four human-decision walkthroughs

Use the **same prompt above on each fresh trip**. The model's wording can
vary; identify the notes by their meaning and date rather than exact title.

| Walkthrough | What to do after reviewing the draft | What to show afterwards |
| --- | --- | --- |
| **1. Approve** | Leave both notes selected and click **Approve all items**. | Two new notes appear on 12 and 13 November; the dinner remains. Three saved items in total. |
| **2. Correct** | On the fresh correction trip, expand **Correct item 1**, change its title to `Human-corrected preparation`, leave both selected, then click **Save corrections**. | Two new notes are saved, including the edited title. Three saved items in total. |
| **3. Partial** | On the fresh partial trip, untick the day-bag note and click **Save selected items**. | Only the travel-documents note is added; the day-bag note is absent. Two saved items in total. |
| **4. Reject** | On the fresh rejection trip, click **Reject plan**. | **Nothing was saved: you rejected this plan.** Only the original dinner remains. |

For the main video, approve is enough to show the complete save path; use
the other three as separately recorded backup footage if the group has time.
Each run takes one decision. Do not try to demonstrate rejection by rejecting
an already-approved run: that correctly returns `MULTI_AGENT_ALREADY_DECIDED`.
If any draft fails the precheck, reject it or correct the actual problem;
do not approve it just to match the expected item counts.

### Optional saved-evidence rehearsal, not a verified recording prompt

Only try this on another fresh trip with the dinner above:

```text
Draft exactly two short preparation reminders for the saved dinner: one on 12 November and one on 13 November. Use the saved dinner's id as source evidence. Do not repeat the dinner or invent venues. Use null times and optional details; keep titles brief.
```

This request exposed missing source IDs and wrong dates in earlier runs, even
with an approving Reviewer. It is **not** the prompt used for the four passing
walkthroughs. Check the dates and exact source IDs against the tool evidence;
reject an incorrect draft. Use it to rehearse human scrutiny, not to claim
saved-booking accuracy has already been established. The main prompt produces
general notes, whose null source IDs are allowed.

### Show the same run in the terminal

In the Multi-Agent Python environment, substitute the Run ID visible on the
page. For the isolated recording stack:

```powershell
python -m multi_agent_service --url http://127.0.0.1:18313 show <run_id>
python -m multi_agent_service --url http://127.0.0.1:18313 export <run_id> --format markdown
```

For the standard stack, use `http://127.0.0.1:8013`. Say that a prepared run
was generated before recording; do not present it as instantaneous generation.

## Student 1 cloud demonstration walkthrough

### Open the deployed application, not localhost

| Page | Address |
| --- | --- |
| Cloud portal | `https://shared-ui.lemonrock-5a94d8cd.australiaeast.azurecontainerapps.io` |
| Student 1 cloud frontend | `https://student-1-frontend.lemonrock-5a94d8cd.australiaeast.azurecontainerapps.io` |

Open both pages a few minutes before recording: the frontends scale to zero
and a cold start can be slow. From the cloud portal, follow the Student 1 link
and keep the browser's HTTPS address visible. Do not use the isolated local
portal on `:18380` for this part.

**Version gate:** checked on 23 October, the latest successful Cloud Deployment
was [run 39870145500](https://github.com/YourNightmareIsOver/TripGenie/actions/runs/39870145500),
SHA `9f51e72331f6f6bb4596851fe5b9bd0257ef0199`. It predates #190 and #189.
It is a dated deployment reference, not the agreed final Release 2 version.
Before the final take, select the team's actual deployment run and record its
SHA; refresh the addresses from that run if they changed. Do not describe
unmerged local PR code as already deployed.

To find the current deployment from any PowerShell directory:

```powershell
gh run list --repo YourNightmareIsOver/TripGenie --workflow cloud-deployment.yml --limit 5 --json databaseId,status,conclusion,headSha,url
```

### Rehearse cloud trip and itinerary CRUD

Use only a disposable trip you create for this take, not a teammate's records.
These browser operations use the deployed frontend, backend and database;
they do not require the local model or local containers.

| Trip field | Value |
| --- | --- |
| Name | `Cloud demo trip - Student 1` |
| Destination | `Melbourne` |
| Start / end date | `2026-11-12` / `2026-11-14` |
| Travellers / status | `2` / `Planned` |
| Notes | `Disposable cloud recording data.` |

| Step | Action on the cloud page | What proves it worked |
| --- | --- | --- |
| **Create a trip** | Click **Create trip**, enter the values above and submit. | The trip detail shows the name, dates and its new trip identifier. |
| **Read and update it** | Click **Edit trip**, change Notes to `Cloud edit confirmed.`, save, then reload the page. | The changed notes survive the reload; this is not just an unsaved form. |
| **Create an itinerary item** | Click **Add itinerary item**. Use title `Cloud coffee stop`, date `2026-11-13`, start `08:00`, end `08:30`, category `Meal`, location `Degraves Street`; submit. | The item appears under **View by day** on 13 November. |
| **Browse and filter** | Select 13 November, or choose that Date and Category **Meal**, then **Apply filters**. | The new item is visible for the requested day/category. Use **Reset filters** afterwards. |
| **Update the item** | Click its **Edit item**, change the title to `Cloud coffee stop - updated`, save and reload. | The updated title is shown on the saved itinerary. |
| **Delete the item** | Click its **Delete item**, then confirm **Delete itinerary item**. | The item disappears, including after reload. |
| **Delete the trip** | Click **Delete trip** and confirm. | Your disposable trip disappears from the trip list. |

This is the full rehearsal/backup sequence, not seven extra beats to squeeze
into the group video. For a short cloud take, show create-trip/delete-trip,
the HTTPS address and deployment evidence. If demonstrating item CRUD instead,
say that its trip was prepared beforehand and delete that trip after recording.

> **Say:** "This is the deployed Student 1 application on Azure Container
> Apps, not my local demo. I can create and update trip and itinerary data,
> reload to read it back, and delete the test records through the cloud UI."

Reload demonstrates persistence in the current running revision, **not durable
storage across deployment**. The cloud uses ephemeral SQLite; a new revision
or restart can reset data. Do not restart or redeploy to demonstrate deletion.

### Explain which features are local-only

AI-Mode, RAG, MCP, Ollama and the Multi-Agent Server run on the host, not in
Azure. The cloud demo is ordinary application functionality; there is no
cloud planner prompt to enter. Cloud and local databases are separate, so
local planner runs and approved items do not automatically appear in Azure.

> **Say:** "The AI workflow runs on our host machines. In Azure we deploy the
> ordinary feature services, with AI disabled. This demonstrates that the
> core application remains usable independently of the local AI stack."

On a final deployment containing #190/#189, disabled AI panels should be
hidden. Older deployments may still display unavailable controls. Check the
actual deployed version before saying the panels are hidden; their visibility
is not proof that cloud AI is available.

### Demonstrate cloud security, not just a padlock

Use 30-45 seconds of optional shared footage, coordinated with Student 5.
Their #195 endpoint-hardening work builds on the deployment identity work;
credit both rather than claiming all shared controls as Student 1's.

| Show on screen | Explain |
| --- | --- |
| Enter the frontend's `http://` address and show the resulting `https://` URL. In DevTools **Network**, preserve the log if you want to show the redirect itself. | Cloud ingress redirects plain HTTP to HTTPS. |
| Reload over HTTPS, select the document request in **Network**, then its response headers. Highlight `Strict-Transport-Security`, `X-Content-Type-Options: nosniff` and `X-Frame-Options: DENY`. | The public frontend sends browser security headers. |
| In the chosen deployment's `cloud-deployment-evidence` artifact, open `cloud-deployment-results.md`: show frontend HTTPS/header checks and the **Security Configuration** table. | Six frontends are public; the twelve backend/database services have internal ingress. Show the configuration check alongside the public-access probes; a 404 alone does not prove isolation. |
| Show the workflow's OIDC login and the registry managed-identity checks, without opening secret values. | GitHub authenticates to Azure through OIDC; apps pull images through managed identity rather than registry passwords. Registry admin and anonymous access are disabled. |

Do not claim user login/authentication, an IP allow-list, CSP, Azure Files
protection or per-service authorization from this evidence. The plain-setting
credential checker is a targeted check, not proof that no possible secret
exists. See [endpoint security](../release-2/cloud-endpoint-security.md) and
[data security](../release-2/cloud-data-security.md) for the implementation.

### Show deployment and release evidence

Open the **Cloud Deployment** Actions run for the version on screen. Show its
commit SHA, successful deployment result, the `production` environment
approval, and the `cloud-deployment-evidence` artifact. Its automated
`cloud-deployment-results.md` is generated for each deployment; the human-written
cloud report in PR #186 is a separate assessment/release narrative.

> **Say:** "This Actions run deployed the version I am showing, after the
> production approval. Its artifact records deployment readiness and security
> checks. That approval authorizes deployment; our final release decision is
> a separate human decision after reviewing the evidence."

Record the deployment URL/SHA and the results you actually observed in the
demonstration guide's evidence record. If the team has not chosen or approved
the final release, leave that decision pending. Do not click **Run workflow**
or approve a deployment just for footage. Keep credentials, subscription IDs
and unrelated browser tabs off screen.

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
