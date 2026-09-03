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
`github-actions[bot]`. This gives every contributor the same current code graph
after pulling `main`, without requiring local Git hooks.

The repository must allow GitHub Actions to write repository contents. In
GitHub, check **Settings → Actions → General → Workflow permissions**.
Branch protection must also permit `github-actions[bot]` to push the generated
artifact commit to `main`.

This workflow intentionally performs code-only extraction, which is
deterministic and does not need an API key. Documentation, paper, and image
changes still require semantic extraction with a supported LLM backend before
their relationships can be added to the committed graph.

## Release 0 local Docker Compose

Ollama is a **host-managed prerequisite**, not a Compose service. Before
starting TripGenie, start Ollama on the host and install the model selected by
`docker-compose.yml`:

```bash
ollama serve
ollama pull llama3.1:8b
curl http://localhost:11434/api/tags
```

On native Linux, Ollama must listen on an address reachable through Docker's
host gateway rather than loopback only:

```bash
OLLAMA_HOST=0.0.0.0:11434 ollama serve
```

Restrict port `11434` to the local Docker bridge with the host firewall; do not
expose it to untrusted networks.

If the operating system already manages Ollama as a service, do not start a
second process; only confirm that `/api/tags` responds and lists the model.
Then build and start the integrated application:

```bash
docker compose --env-file shared/configuration/.env.example up --build -d
```

The shared portal is available at `http://localhost:8080` and links to the
Student 1 frontend at `http://localhost:8081`. Student 1 backend, database, and
shared AI-Mode ports remain internal to Compose. The shared `ai-mode` container
reaches host Ollama through `host.docker.internal:11434`; the Linux
`host-gateway` mapping is included in Compose.

Trip and itinerary CRUD remains available when Ollama is stopped or its model
is absent. AI suggestion requests report the dependency failure separately.

Useful status and log commands:

```bash
docker compose --env-file shared/configuration/.env.example ps
docker compose --env-file shared/configuration/.env.example logs -f student-1-frontend student-1-backend student-1-database ai-mode
curl http://localhost:8081/health
curl http://localhost:8081/ready
```

Reset Compose containers and persisted application volumes with:

```bash
docker compose --env-file shared/configuration/.env.example down -v --remove-orphans
```

This does not remove Ollama or models installed on the host. If AI-Mode cannot
reach Ollama, verify the host binding and firewall access to port `11434`. On
native Linux, confirm that the service is not listening on loopback only.
Compose never installs Ollama or downloads models.
