# Student 1 Release 1 evidence register

Prepared: **2 October 2026 (UTC)** · Owner: Aaditya Rai (`aadirai31`) ·
Issue: [#132](https://github.com/JulianKirk/TripGenie/issues/132)

Live evidence was captured from one run of `main` at
[`aec615c`](https://github.com/JulianKirk/TripGenie/commit/aec615cf388ae13bb51567cd00186b021a85516e)
(PR #145 merge). Every row below links to the captured output; nothing is
reconstructed or simulated. Rows marked **Pending** have no evidence yet.

## Environment

| Item | Value (from [01-versions.txt](evidence/student-1/01-versions.txt)) |
| --- | --- |
| Machine | Apple M2, 16 GB, macOS 14.0, Docker 29.5.3, Compose v5.1.4 |
| Host Python | 3.12.2 |
| Models (Ollama) | `llama3.1:8b` (generation), `nomic-embed-text` (embeddings, 768 dims), `qwen2.5:0.5b` (allowed) |
| Host services | AI-Mode `127.0.0.1:8006`, RAG `127.0.0.1:8011`, MCP `127.0.0.1:8012/mcp`, started per the [host services runbook](local-host-services-runbook.md) |
| Compose | Project of feature + shared-portal containers; Student 1 frontend `localhost:8081`, backend `127.0.0.1:18001` |
| Demo data | Seed trip `trip_2026_melbourne_food_trail` (city-only destination "Melbourne") |

## Requirement-to-evidence matrix

| # | Requirement / rubric criterion | Evidence | Command / action | Expected | Actual | Status |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Compose runs only feature containers; no AI-Mode, MCP, RAG, Ollama or agentic service | [02](evidence/student-1/02-compose-and-host-connectivity.txt) | `docker compose config --services`; `docker compose ps` | No host-only service in Compose; feature services running | 23 configured services (15 feature + 3 shared-portal + 5 one-shot aggregate targets); none match `ai-mode/mcp/rag/ollama/agent`; 18 containers running, Student 1 three healthy | Pass |
| 2 | Containerised backends reach host services | [02](evidence/student-1/02-compose-and-host-connectivity.txt) | `docker compose exec -T student-1-backend python -c "urlopen('http://host.docker.internal:<port>/health')"` | HTTP 200 from 8006, 8011, 8012 | `200 ok ai-mode`, `200 ok rag-server`, `200 healthy tripgenie-mcp` | Pass |
| 3 | Terminal validation: AI-Mode and RAG health/readiness | [03](evidence/student-1/03-host-services-and-rag-terminal.md) | `curl /health`, `/ready` | Healthy; RAG index ready | AI-Mode ok (Ollama models present); RAG ready, 9 documents, 124 chunks, `nomic-embed-text`, 768 dims (index path redacted) | Pass |
| 4 | RAG knowledge sources and ingestion | [03](evidence/student-1/03-host-services-and-rag-terminal.md), [`config/sources.json`](../../../ai-services/rag-server/config/sources.json) | `python -m rag_service ingest --rebuild` | Manifest sources chunked and embedded through AI-Mode | 9 documents, 124 chunks embedded, 768 dims, 3.7 s | Pass |
| 5 | Terminal RAG: grounded answer with citations and confidence | [03](evidence/student-1/03-host-services-and-rag-terminal.md) | `POST :8011/query` "What are good day trips from Melbourne?" | Answer, `high`/`medium`/`low`, citations resolved from retrieved chunks | `high` (max score 0.832), 1 citation `travel-destination-guides` chunk, 73.1 s | Pass |
| 6 | Terminal RAG: insufficient context | [03](evidence/student-1/03-host-services-and-rag-terminal.md) | `POST :8011/query` live-weather and sourdough questions | Fixed insufficient answer, no citations, no unsupported text | Weather (0.611): generation ran, model verdict insufficient, 51.3 s; sourdough (0.428): generation skipped, 1.08 s | Pass |
| 7 | Terminal MCP: registered tools, input/output, boundaries | [04](evidence/student-1/04-mcp-terminal.md) | `python -m tripgenie_mcp inspect`; `call trip_get_context`, `activities_search`, `transport_search`; unknown tool; extra argument | Tools listed with schemas/annotations; structured results; invalid calls rejected | 19 tools, all `additionalProperties: false`; three calls `ok` (0.7-2.2 s); `trip_delete` "Unknown tool"; extra arguments rejected | Pass |
| 8 | Backend/API MCP returns a valid tool result | [05](evidence/student-1/05-backend-api-rag-mcp-ai.md) | `POST /api/trips/{id}/mcp-options` `{"country":"Australia"}` and `{}` | 5 read-only tools via host MCP, `persisted: false`; without country, location searches skipped | 5 ok (0.52 s); `{}` → 3 ok, 2 skipped with reason (0.03 s) | Pass |
| 9 | Backend/API RAG grounded and insufficient | [05](evidence/student-1/05-backend-api-rag-mcp-ai.md) | `POST /api/trips/{id}/rag-query` | Contract preserved; citations/confidence; insufficient path | Grounded `high`, 1 citation, 34.7 s; insufficient, no citations, 0.88 s | Pass |
| 10 | Frontend MCP interaction | [07](evidence/student-1/07-frontend-screenshots.md), screenshots 04-05 | "Find trip options" with/without country | Tool cards; nothing saved; skipped reasons | 5 cards, "Nothing was saved" (1.4 s); 2 Skipped cards without country | Pass |
| 11 | Frontend RAG grounded + insufficient | [07](evidence/student-1/07-frontend-screenshots.md), screenshots 02-03 | "Ask the knowledge base" | Confidence badge, answer, sources; insufficient state | "High confidence" + 1 source (26.2 s); "Insufficient context" state (32.5 s) | Pass |
| 12 | Release 0 regression: CRUD and database operations | [06](evidence/student-1/06-release-0-crud.md), screenshot 01 | List/read trips; itinerary item create → read → update → delete | 200/201/200/200, then 404; seed data unchanged | 10 trips; item lifecycle succeeded; final item list equals seed | Pass |
| 13 | Release 0 AI-Mode suggestions still work | [05](evidence/student-1/05-backend-api-rag-mcp-ai.md), screenshot 06 | `POST /ai-suggestions`; frontend "Generate draft suggestions" | Drafts, `persisted: false`, approval required | 2 drafts, `persisted: false`, `approval_required: true` (API 79.0 s, UI ≤ 46 s). Draft quality was sparse (see register note) | Pass (functional) |
| 14 | CI succeeds with runtime MCP/RAG disabled | [08](evidence/student-1/08-ci-disabled-modes.md) | [Run 36957328723](https://github.com/JulianKirk/TripGenie/actions/runs/36957328723) | Student 1 CI green; disabled routes return explicit codes; no host-only service in Compose | 5/5 jobs passed; `RAG_ENABLED=false`, `MCP_ENABLED=false`; `503 RAG_DISABLED`, `503 MCP_DISABLED`; RAG tests 41 passed | Pass on branch `c1ff13d`; **merge pending** ([PR #159](https://github.com/JulianKirk/TripGenie/pull/159)) |
| 15 | Resilience: host services disabled/unavailable do not break CRUD | [08](evidence/student-1/08-ci-disabled-modes.md); backend tests in [#144](https://github.com/JulianKirk/TripGenie/pull/144) | CI Compose job with MCP/RAG disabled | CRUD and readiness unaffected | CI Compose readiness passed with both disabled. A live stop-the-service test was not run, to avoid disturbing the shared stack | Pass (disabled); live outage not captured |
| 16 | Agentic loop, MCP mode | Pending | Team-owned: agentic loop code merged in [PR #141](https://github.com/JulianKirk/TripGenie/pull/141) (`d020eb6`, Mark) after this capture's base commit | Loop run in MCP mode with recorded checks and review | Not captured by Student 1 | **Pending** (from #141 owner / issue #131) |
| 17 | Agentic loop, RAG mode | Pending | As above (`ai-services/agentic-loop/checks/rag.json`) | Loop run in RAG mode with recorded checks and review | Not captured by Student 1 | **Pending** (from #141 owner / issue #131) |
| 18 | Contribution log with identifiable commits | [Contribution log](student-1-contribution-log.md) | `gh pr view`, `git log origin/main` | PRs and commits attributable to `aadirai31` | 6 merged PRs, 1 open, this branch | Pass |
| 19 | Group video (≤ 10 min) with Student 1 segment | [Demo runbook](student-1-demo-runbook.md) | Recording | Published URL, Aaditya on screen | Not recorded | **Pending** |

Note on row 13: the two drafts were "Food Court" and "Queen Victoria Market
Tour", with no times, locations or rationale. This is reported as-is; it is
local-model quality, not a contract failure, and drafts are never saved
without user review.

## Measured latency (this machine, warm models)

| Path | Observed |
| --- | --- |
| RAG grounded answer (direct / backend / UI) | 73.1 s / 34.7 s / 26.2 s |
| RAG insufficient, generation skipped | 0.07-1.08 s |
| RAG insufficient, model verdict | 32.4-51.3 s |
| MCP single tool (CLI) | 0.7-2.2 s |
| MCP options, 5 tools (backend / UI) | 0.52 s / 1.4 s |
| Release 0 AI suggestions (backend / UI) | 79.0 s / ≤ 46 s |
| Itinerary CRUD request | 8-58 ms |

## Sanitisation

Evidence contains no credentials, prompts, vectors or generated index files.
The RAG index path is redacted. Citation excerpts are the short (about 240-character)
snippets returned by the contract from committed repository documents. Long
tool payloads are summarised (counts, ids, first item). Trip data is seeded
demo data only.
