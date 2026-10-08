# Release 1 Shared RAG Plan and Evidence Index

Student 1's Release 1 responsibility in this plan is the initial shared,
non-containerized RAG server. Other Release 1 services are owned and planned
separately.

## Planning and architecture

- [Shared RAG architecture](../../architecture/release-1-shared-rag-architecture.md)
- [Shared RAG contract](../../architecture/release-1-rag-contract.md)
- [Student 1 RAG delivery plan](./student-1-release-1-plan.md)
- [Student 1 data models retained from Release 0](../../architecture/student-1-data-models.md)

## Running locally

- [Local host services runbook](./local-host-services-runbook.md): Ollama,
  AI-Mode, RAG, and MCP on the host, then Docker Compose.

## Evidence rules

- Store only reproducible, sanitized evidence.
- Include the command/request, date, relevant versions/configuration, expected
  result, actual result, and commit or workflow URL.
- Do not claim successful execution before it occurs.
- Do not commit credentials, full prompts, retrieved source bodies, generated
  vectors/indexes, personal trip data, or machine-specific absolute paths.
- Keep individual contribution records traceable to GitHub commits and PRs.

## Student 1 Release 1 evidence and report material

- [Evidence register](./student-1-evidence-register.md): requirement →
  evidence → command → expected → actual → status.
- [Captured evidence](./evidence/student-1/): versions, Compose and
  container-to-host checks, terminal RAG/MCP, backend API, Release 0 CRUD,
  frontend screenshots, CI with MCP/RAG disabled.
- [Contribution log](./student-1-contribution-log.md)
- [Report contribution](./student-1-report-contribution.md)
- [Demo runbook and Q&A notes](./student-1-demo-runbook.md)
