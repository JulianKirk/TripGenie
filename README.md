# TripGenie – AI Smart Travel Companion

> **Course:** 41026 Advanced Software Development (Spring 2026)  
> **Team:** Group 07  
> **Repository:** [https://github.com/JulianKirk/TripGenie](https://github.com/JulianKirk/TripGenie)

---

## 1. Project Overview
TripGenie is an AI Smart Travel Companion microservices application built with Docker, HTMX, Python, SQLite, and Ollama.

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
│       ├── integration-ci.yml
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
│   ├── ai-mode/
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

### Install Graphify and the Git hooks

Install Graphify once, then run the repository setup script:

```bash
uv tool install --upgrade graphifyy
./scripts/setup-graphify.sh
```

The official Graphify `post-commit` hook incrementally rebuilds the graph after
code commits. Its `post-checkout` hook rebuilds after switching branches. Hook
work runs in the background; its log is written to
`~/.cache/graphify-rebuild.log`.

Git does not distribute local hooks when a repository is cloned, which is why
each contributor must run the setup script once. Confirm the installation at
any time with:

```bash
graphify hook status
```

The hooks update code relationships without an LLM. They deliberately ignore
documentation and image changes. `graphify update .` refreshes code only; after
changing documentation or images, run a full semantic extraction with a
supported LLM backend configured:

```bash
graphify extract .
```

To refresh only code relationships from the repository root, run:

```bash
graphify update .
```
