# TripGenie – AI Smart Travel Companion

> **Course:** 41026 Advanced Software Development (Spring 2026)  
> **Team:** Group 07  
> **Repository:** [https://github.com/JulianKirk/TripGenie](https://github.com/JulianKirk/TripGenie)

---

## 1. Project Overview
TripGenie is an AI Smart Travel Companion microservices application built with Docker-hosted app services, HTMX, Python, SQLite, and a host-managed Ollama runtime.

---

## 2. Team Member Feature Allocation

| Student | Name | Feature Module | CI Workflow |
| :---: | :--- | :--- | :--- |
| **Student 1** | Aaditya Rai | Trip & Itinerary Management | `.github/workflows/student-1-ci.yml` |
| **Student 2** | Mark Ureta | Accommodation Management | `.github/workflows/student-2-ci.yml` |
| **Student 3** | Ronit Jain | Transport Management | `.github/workflows/student-3-ci.yml` |
| **Student 4** | Julian Kirk (Lead) | Activities & Attractions Management | `.github/workflows/student-4-ci.yml` |
| **Student 5** | Caleb Huynh | Budget & Expense Management | `.github/workflows/student-5-ci.yml` |

---

### Deterministic CI readiness baseline

Every ordinary service CI workflow uses `scripts/ci/wait_for_http.py` for its
final HTTP health or readiness probe. The policy is intentionally small and
fixed: at most eight attempts, a two-second interval between failed attempts,
and a two-second timeout for each HTTP request. The probe prints every attempt
and the elapsed time when the service responds, giving each workflow a
consistent, non-agent startup/readiness check and an auditable Actions log.

The Agentic Loop is a local validation harness, not part of CI. It keeps its
own retry and endpoint-latency policy, and its deterministic checks remain
additional coverage rather than the definition of this minimum baseline.

---

### Release 2 local pre-commit security gate

Install the hook once per clone using Python 3.11 or newer (activate your
virtual environment first):

```powershell
python -m pip install -r scripts\security\requirements.txt
python -m pre_commit install
python -m pre_commit run security --all-files --verbose
```

On macOS/Linux, use `scripts/security/requirements.txt` in the install command.
Normal `git commit` now runs the same blocking gate before creating a commit.
The isolated hook environment pins Ruff, detect-secrets and pip-audit; it does
not depend on which feature packages happen to be installed locally.

- **Ruff:** all stable `S` (Bandit security) rules across the repository, with an
  explicit security configuration that service overrides cannot disable.
  Only pytest assertions are exempt from `S101`; reviewed false positives have
  individual, explained `noqa` annotations.
- **detect-secrets:** all detectors over tracked and non-ignored new files,
  including non-Python configuration. Verification network calls are disabled
  so possible secrets are never sent to provider APIs. Synthetic test fixtures
  have inline allowlist explanations. The two generated Graphify checksum
  exceptions match an exact file, detector and fingerprint in
  `scripts/security/secret-allowlist.toml`; there is no bulk accepted baseline
  or generated-directory exclusion.
- **pip-audit:** resolves and audits runtime and every optional/dev dependency
  from all service `pyproject.toml` files, plus every `requirements*.txt`,
  including the agentic loop and security tools. Transitive dependencies are
  included. No vulnerability IDs are ignored. Resolution/network failures,
  skipped dependencies, malformed output and timeouts fail the gate.

Each run copies the Git-eligible files to a temporary snapshot, then runs all
three checks even if one fails. During a normal commit, pre-commit temporarily
stashes unstaged tracked edits and restores them afterwards. Manual
`--all-files` scans the current working tree, including non-ignored new files.
Ignored local credentials, virtual environments, caches and Git history are
not scanned; this is not a history scan or a substitute for secret rotation.
Do not bypass the hook with `--no-verify` or `SKIP=security`.

The complete JSON report is retained locally at
`.git/security-reports/latest.json` (use `git rev-parse --git-path
security-reports/latest.json` for worktrees). It contains timestamps, HEAD,
Python/platform, scanned file and manifest lists, a content SHA-256, commands,
tool versions, durations, exit codes, diagnostics, hashed secret findings and
all resolved dependency versions/advisories. A failed run replaces the previous
report, preventing stale success evidence. Dependency results apply to the
versions resolved on that Python/platform at scan time, not to an existing
deployed environment; scans require access to the package/advisory services.

To retain named evidence outside the repository for the Release 2 technical
report and the agentic-loop Testing Review:

```powershell
python scripts\security\scan.py --report "$env:TEMP\tripgenie-pre-commit-security.json"
python -m pytest tests\ci -q
```

Preserve the JSON report and verbose hook output with the tested branch/HEAD
and human review decision. Demonstrate both a clean pass and a blocked unsafe
change in the showcase. The report can be supplied as evidence to the separate
Testing Review; this gate does not call an LLM or claim that review ran.
Promote evidence to `docs/reports/release-2` only when explicitly preparing the
release submission. Local hooks must be installed by every contributor; a
passing scan alone does not fulfil the technical-report or showcase criteria.

---

## 3. Project Repository Structure

```text
TripGenie/
├── .github/
│   └── workflows/
│       ├── student-1-ci.yml … student-5-ci.yml
│       ├── shared-ci.yml
│       ├── ai-mode-ci.yml
│       ├── non-functional-ci.yml
│       ├── workflow-policy-ci.yml
│       ├── graphify-update.yml
│       └── cloud-deployment.yml
├── AGENTS.md               # repository-wide agent and contributor rules
├── README.md
├── .gitignore
├── ruff.toml               # shared lint and format policy
├── docker-compose.yml      # containerised feature services only
├── docs/
│   ├── architecture/
│   │   └── decisions/      # architecture decision records
│   ├── designs/
│   └── reports/
│       ├── release-0/
│       ├── release-1/
│       └── release-2/
├── graphify-out/           # generated knowledge graph; do not hand-edit
├── shared/                 # country, city and currency reference data, landing page
│   ├── shared-service.md
│   ├── pyproject.toml
│   ├── backend/
│   ├── database/
│   ├── docs/
│   ├── tests/
│   ├── frontend/
│   │   ├── Dockerfile
│   │   ├── index.html
│   │   └── theme.css
│   └── configuration/
│       └── .env.example
├── student-1/              # same layout for student-2 … student-5
│   ├── AGENTS.md
│   ├── pyproject.toml
│   ├── frontend/
│   ├── backend/
│   ├── database/
│   └── tests/
├── student-2/
├── student-3/
├── student-4/
├── student-5/
├── ai-services/            # host-run, never Compose services
│   ├── ai-mode/            # the only service that talks to Ollama
│   ├── mcp-server/         # shared MCP tools over public feature APIs
│   ├── rag-server/         # shared retrieval and grounded responses
│   ├── agentic-loop/       # local validation harness, incl. MCP and RAG modes
│   └── multi-agent-server/ # Release 2 Planner → Worker → Reviewer → human review (:8013)
├── scripts/
│   ├── run-app.sh          # starts Compose plus the host AI services
│   ├── ci/
│   ├── test/
│   └── deploy/
└── tests/
    └── ci/                 # tests for shared CI scripts
```

Students 1–3 build from a single `Dockerfile` in their slice root. Students 4
and 5 keep one `Dockerfile` in each of `frontend/`, `backend/` and
`database/`. Some slices also include a `docs/` folder for API and
object-model documentation.

---

## 4. Repository Knowledge Graph

Graphify builds a navigable knowledge graph of the services, APIs,
documentation, and source relationships in this repository. The portable
outputs are committed so every team member can use them without rebuilding
first:

- `graphify-out/graph.html` — interactive graph that opens in a browser
- `graphify-out/GRAPH_REPORT.md` — architecture report and suggested queries
- `graphify-out/graph.json` — raw graph used by Graphify queries

### Using Graphify

The repository's initial agent guidance lives in `AGENTS.md`. It tells coding
agents to consult the committed graph for architecture and dependency
questions. Developers can open the report or interactive graph without any
local setup. To run focused terminal queries, optionally install Graphify:

```bash
uv tool install --upgrade graphifyy
graphify query "how do the backend services reach their databases?"
```

`graphify update .` refreshes code only. After changing documentation or
images, a full semantic extraction requires a supported LLM backend:

```bash
graphify extract .
```

### Central graph updates on GitHub

The `Graphify Update` GitHub Actions workflow runs after changes are merged to
`main`. It performs the no-LLM code update and, when the portable graph changes,
commits only `graph.json`, `graph.html`, and `GRAPH_REPORT.md` as
`github-actions[bot]` on the `automation/graphify-update` branch. The workflow
opens or updates a pull request for those generated outputs so repositories that
require all changes to reach `main` through a pull request remain protected.
After that pull request is merged, every contributor receives the same current
code graph when they next pull `main`, without requiring local Git hooks.

The repository must allow GitHub Actions to write repository contents and create
pull requests. In GitHub, check **Settings → Actions → General → Workflow
permissions**, then enable **Allow GitHub Actions to create and approve pull
requests**. The workflow creates the graph pull request but never approves or
merges it.

This workflow intentionally performs code-only extraction, which is
deterministic and does not need an API key. Documentation, paper, and image
changes still require semantic extraction with a supported LLM backend before
their relationships can be added to the committed graph.

## Local Docker Compose

Ollama, AI-Mode, MCP, RAG, and the validation loop are **host processes**.
Compose runs only the shared reference service and the feature frontends,
backends, and databases. Start the host services first, in the order given by
the [local host services runbook](docs/reports/release-1/local-host-services-runbook.md),
then:

```bash
docker compose --env-file shared/configuration/.env.example up --build -d
docker compose --env-file shared/configuration/.env.example ps
```

The portal is at `http://localhost:8080`. Backends reach host AI-Mode, RAG, and
MCP at `http://host.docker.internal:8006`, `:8011`, and `:8012/mcp`; each such
backend declares the Linux `host-gateway` mapping. Student 1, 3, 4, and 5
public APIs are published on **host loopback** ports 18001, 18003, 18008, and
18005 (Student 2 on 9000) for host MCP. Database APIs remain private. See the
[Student 4 MCP guide](student-4/docs/mcp-assistant.md) for the activity
assistant demonstration.

Ordinary feature workflows remain usable if host AI services are unavailable.
AI requests report dependency failures separately. The Student 4 assistant
never silently substitutes direct catalogue calls when MCP fails.
`shared/configuration/.env.cloud` is the cloud profile: every AI switch off,
and `TRIPGENIE_FORWARDED_ALLOW_IPS=*` so the Python frontends trust the Azure
HTTPS ingress's `X-Forwarded-Proto` and render `https://` page URLs. Without it
(as locally), uvicorn keeps its loopback-only default.
Off localhost, `TRIPGENIE_PORTAL_URL` (each frontend) and `STUDENT1_UI_URL` to
`STUDENT5_UI_URL` (the portal) set the browser-facing addresses.

```bash
docker compose --env-file shared/configuration/.env.example logs -f student-1-frontend student-1-backend student-1-database
curl http://localhost:8081/health
curl http://localhost:8081/ready
```

Stop the containers and keep their data with `docker compose down`. Reset
persisted application volumes only when that is intended:

```bash
docker compose --env-file shared/configuration/.env.example down -v --remove-orphans
```

Neither command touches host Ollama, its models, or the RAG index. Compose
never installs Ollama or downloads models.

## Release 1 shared RAG planning

The Release 1 shared RAG server runs directly on the local host, outside Docker
Compose. Its architecture, API contract, and Student 1 delivery plan are
documented here:

- [Shared RAG architecture](docs/architecture/release-1-shared-rag-architecture.md)
- [Shared RAG contract](docs/architecture/release-1-rag-contract.md)
- [Shared RAG plan and evidence index](docs/reports/release-1/README.md)
- [Shared RAG setup and operation](ai-services/rag-server/README.md)
