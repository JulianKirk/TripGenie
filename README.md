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

The Agentic Loop keeps its separate retry and endpoint-latency policy. Its
deterministic checks remain additional coverage rather than the definition of
this minimum baseline.

---

## 3. Project Repository Structure

```text
TripGenie/
├── .github/
│   └── workflows/
│       ├── student-1-ci.yml
│       ├── student-2-ci.yml
│       ├── student-3-ci.yml
│       ├── student-4-ci.yml
│       ├── student-5-ci.yml
│       ├── shared-ci.yml
│       └── cloud-deployment.yml
├── README.md
├── .gitignore
├── docker-compose.yml
├── docs/
│   ├── architecture/
│   └── reports/
│       ├── release-0/
│       ├── release-1/
│       └── release-2/
├── shared/
│   ├── shared-service.md
│   ├── backend/
│   ├── database/
│   ├── docs/
│   ├── tests/
│   ├── frontend/
│   │   ├── index.html
│   │   ├── css/
│   │   ├── js/
│   │   └── assets/
│   └── configuration/
├── student-1/
│   ├── frontend/
│   ├── backend/
│   ├── database/
│   ├── tests/
│   └── Dockerfile
├── student-2/
├── student-3/
├── student-4/
├── student-5/
├── ai-services/
│   ├── ai-mode/            # shared: the only service that talks to Ollama
│   ├── agentic-loop/
│   ├── mcp-server/
│   ├── rag-server/
│   └── multi-agent-server/
└── scripts/
    ├── build/
    ├── test/
    └── deploy/
```

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
