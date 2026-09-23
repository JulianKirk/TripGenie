# Student 1 Release 1 Plan

Owner: Aaditya Rai

Feature: Trip and Itinerary Management

Tracking issue: [#133](https://github.com/JulianKirk/TripGenie/issues/133)

Contract issue: [#121](https://github.com/JulianKirk/TripGenie/issues/121)

## 1. Objectives

Student 1 will:

- preserve Release 0 Trip and Itinerary CRUD and advisory AI suggestions;
- establish the initial shared non-containerized RAG server;
- access the shared host MCP and RAG services through the Student 1 backend;
- use read-only tools from Accommodation, Transport, Activities, and
  Budget/Expenses when planning a coherent itinerary;
- return grounded answers with citations, confidence, and explicit
  insufficient-context handling; and
- keep every generated itinerary item as a reviewable draft until explicit
  user approval and normal CRUD validation.

## 2. Delivery sequence

| Wave | Issues | Deliverable |
| ---: | --- | --- |
| 1 | [#121](https://github.com/JulianKirk/TripGenie/issues/121) | Documentation-only contract gate and implementation plan. |
| 2 | [#122](https://github.com/JulianKirk/TripGenie/issues/122), [#123](https://github.com/JulianKirk/TripGenie/issues/123), [#124](https://github.com/JulianKirk/TripGenie/issues/124), [#125](https://github.com/JulianKirk/TripGenie/issues/125) | **One Shared RAG PR** containing the host AI-Mode embedding boundary, RAG server, ingestion/index, grounded query, tests, and service documentation. |
| 2 | [#126](https://github.com/JulianKirk/TripGenie/issues/126) | Shared host MCP server and normalized read-only tools; team owner to confirm. |
| 3 | [#127](https://github.com/JulianKirk/TripGenie/issues/127) | Student 1 MCP/RAG clients and bounded itinerary planner. |
| 4 | [#128](https://github.com/JulianKirk/TripGenie/issues/128) | Student 1 accessible MCP and RAG frontend flows. |
| 5 | [#129](https://github.com/JulianKirk/TripGenie/issues/129), [#130](https://github.com/JulianKirk/TripGenie/issues/130), [#131](https://github.com/JulianKirk/TripGenie/issues/131) | Host connectivity, CI disabled modes, and agentic-loop validation. |
| 6 | [#132](https://github.com/JulianKirk/TripGenie/issues/132) | Integrated validation, report evidence, showcase, and Q&A preparation. |

The Shared RAG PR closes #122-#125 together. It must not absorb MCP, feature
frontend/backend integration, Compose, or evidence work.

## 3. Release 1 rubric traceability

| Criterion | Planned evidence |
| --- | --- |
| 1. Project setup and architecture | Integrated architecture, host/container boundary, repository structure, ports, contracts, and request-flow diagrams. |
| 2. Student feature microservices | Student 1 frontend/backend/database regression results for CRUD, API responses, persistence, and Release 0 AI-Mode. |
| 3. MCP server integration | Registered tool catalogue, boundaries, terminal invocation, and Student 1 frontend/backend interaction using another feature's tool. |
| 4. RAG and grounded responses | Corpus/manifest, ingestion summary, retrieval trace, valid citations/confidence, grounded frontend response, and insufficient-context case. |
| 5. Shared agentic loop | Sanitized outputs from separate MCP and RAG validation modes. |
| 6. DevOps and GitHub Actions | Successful `student-1-ci.yml` URL/log with live AI-Mode, MCP, and RAG explicitly disabled. |
| 7. Docker Compose deployment | `docker compose config`, running feature containers, absence of host AI services from Compose, and successful container-to-host calls. |
| 8. Integrated working software | End-to-end validation across Student 1 and Students 2-5 plus degraded-service regression. |
| 9. Technical report and evidence | Requirements, architecture, design, validation, limitations, repository/video links, contribution log, and commits. |
| 10. Demonstration and Q&A | Aaditya demonstrates Student 1 MCP/RAG and explains tool boundaries, grounding, confidence, insufficient context, and non-containerization. |

## 4. Validation matrix

| Scenario | Expected result |
| --- | --- |
| Release 0 Trip/Itinerary CRUD | Unchanged and operational. |
| Release 0 AI suggestion | Draft remains advisory and review-before-save. |
| MCP success | Student 1 frontend displays a valid structured result returned through its backend and a registered cross-service tool. |
| MCP partial provider | Available observations remain marked partial; failure is not converted to empty success. |
| RAG success | Answer contains only index-resolved citations and a server-calculated confidence category. |
| RAG insufficient context | Fixed response, `insufficient_context=true`, no generation, and no citations. |
| Host service disabled | MCP/RAG action reports disabled; CRUD remains ready. |
| Host service unavailable/timeout | Explicit dependency error; no success-shaped fallback and no CRUD outage. |
| Planner draft | Uses authoritative IDs, respects trip/collision/budget/capacity rules, and is not persisted. |
| CI | All Student 1 and RAG contract tests pass without host services or model downloads. |
| Compose | Feature containers run; AI-Mode, MCP, RAG, Ollama, and agentic loop are absent as services. |

## 5. Risks and mitigations

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Specific Release 1 brief conflicts with older containerization wording | Incorrect deployment loses rubric marks. | Treat the assessment brief as controlling and document the host boundary in architecture, Compose, CI, and evidence. |
| Other feature APIs use different methods/envelopes/types | Planner becomes coupled and brittle. | Normalize only in MCP adapters; preserve authoritative IDs, nullability, exact money, and pricing basis. |
| Student 5 budget summary calls back to Student 1 | Synchronous cycle or exhausted workers. | Call outside write transactions with short bounded timeouts and explicit partial results. |
| Small local model or limited GPU is slow | Demo timeout or repeated submission. | Bound candidates/context, use one approved small model, align timeout layers, warm the model, and show progress. |
| Retrieval score is mistaken for certainty | Unsupported confident answer. | Calibrate thresholds against a versioned query set and require valid citation coverage. |
| Prompt injection in indexed documents | Grounding rules are overridden. | Treat chunks as untrusted data, allowlist sources, validate citation IDs, and never execute retrieved instructions. |
| AI/MCP/RAG outage blocks normal use | Release 0 regression. | Keep enable flags optional and Student 1 readiness database-only. |
| Generated IDs or records are treated as real | Invalid itinerary associations. | Accept only identifiers returned by authoritative search/detail tools; require human review. |
| One large RAG PR becomes hard to review | Defects hidden in an oversized diff. | Keep commits separated by AI embedding, foundation, ingestion, query, and docs/tests while retaining one integrated PR. |
| Evidence includes secrets or unverified claims | Security/academic-integrity failure. | Store sanitized metadata and links only; never claim checks that were not executed. |

## 6. Contribution and evidence checklist

- [ ] Contract/architecture PR and issue link.
- [ ] Shared RAG PR closing #122-#125 with focused commits.
- [ ] Student 1 backend and frontend PRs.
- [ ] Successful CI workflow URL.
- [ ] Host startup commands and versions.
- [ ] RAG ingestion summary and calibrated query set.
- [ ] MCP terminal tool result.
- [ ] Grounded RAG result with citations/confidence.
- [ ] Insufficient-context RAG result.
- [ ] Student 1 browser MCP and RAG evidence.
- [ ] Release 0 regression and degraded-mode evidence.
- [ ] Compose status and host-connectivity evidence.
- [ ] Agentic-loop MCP and RAG mode outputs.
- [ ] Known limitations, contribution log, demo segment, and Q&A notes.
