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
│       ├── shared-ci.yml
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
