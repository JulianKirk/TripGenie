# Student 1 Shared RAG Delivery Plan

Owner: Aaditya Rai

Feature: Initial shared non-containerized RAG server

Tracking issue: [#133](https://github.com/JulianKirk/TripGenie/issues/133)

Contract issue: [#121](https://github.com/JulianKirk/TripGenie/issues/121)

## 1. Scope

Student 1 will deliver:

- the bounded AI-Mode embedding operation required by RAG;
- a host-run FastAPI RAG service outside Docker Compose;
- allowlisted source ingestion and a local SQLite vector index;
- feature-scoped retrieval and grounded generation;
- citations resolved from indexed metadata;
- server-calculated confidence and explicit insufficient-context behavior;
- deterministic tests using fake transports and vectors; and
- setup, contribution, operation, and evidence documentation.

This plan does not specify or implement the separately owned tool server,
tool catalogue, or tool-backed itinerary planner.

## 2. One-PR delivery

Issues [#122](https://github.com/JulianKirk/TripGenie/issues/122),
[#123](https://github.com/JulianKirk/TripGenie/issues/123),
[#124](https://github.com/JulianKirk/TripGenie/issues/124), and
[#125](https://github.com/JulianKirk/TripGenie/issues/125) will be delivered in
one Shared RAG pull request.

| Order | Issue | Deliverable |
| ---: | --- | --- |
| 1 | #122 | AI-Mode `/embed` contract, embedding allowlist, limits, provider validation, and tests. |
| 2 | #123 | Host RAG package, settings, lifecycle, health/readiness, stable errors, and CLI. |
| 3 | #124 | Manifest validation, safe source loading, heading-aware chunks, embeddings, atomic SQLite rebuild, reuse, and stale-source removal. |
| 4 | #125 | Feature/shared retrieval, grounded query, citation validation, confidence, insufficient context, and API tests. |
| 5 | #122-#125 | Service README, environment examples, source-contribution guide, lint, tests, and PR evidence. |

The PR must not add a RAG Dockerfile or Compose service.

## 3. Implementation sequence

1. Extend AI-Mode with a separate embedding model allowlist and bounded
   `/embed` endpoint.
2. Add the `ai-services/rag-server` Python package and host-only CLI.
3. Define the manifest and seed it with maintained shared and Student 1
   architecture documentation.
4. Implement deterministic chunking, AI-Mode embedding calls, and atomic
   SQLite index replacement.
5. Implement feature plus shared cosine retrieval.
6. Implement grounded JSON generation, citation resolution, confidence, and
   insufficient-context behavior.
7. Add tests for success, boundaries, corrupt data, dependency failures, and
   data-safety rules.
8. Document setup and capture only verified evidence.

## 4. Acceptance criteria

- The service runs locally with `python -m rag_service serve`.
- The index builds locally with `python -m rag_service ingest --rebuild`.
- No RAG runtime is present in Docker Compose.
- RAG calls AI-Mode for both embeddings and generation and never calls Ollama
  directly.
- Only manifest-listed UTF-8 Markdown and text sources inside the repository
  can be ingested.
- Rebuild is atomic, unchanged embeddings are reused, and removed manifest
  sources disappear from the next index.
- Retrieval includes `shared` plus the requested feature and excludes other
  feature-only sources.
- Returned citations map to retrieved chunk IDs and indexed metadata.
- Below-threshold retrieval skips generation and returns the fixed
  insufficient-context response.
- Missing or incompatible indexes and AI-Mode failures use explicit bounded
  error contracts.
- Logs exclude query text, source content, prompts, vectors, and answers.
- Existing feature CRUD remains independent of RAG availability.

## 5. Validation matrix

| Scenario | Expected result |
| --- | --- |
| Valid ingestion | Manifest sources are chunked, embedded through AI-Mode, and atomically indexed. |
| Unchanged rebuild | Existing compatible embeddings are reused. |
| Removed source | Stale documents and chunks are absent after rebuild. |
| Invalid path | Absolute, traversal, secret, database, log, and unsupported paths are rejected. |
| RAG success | The answer has only index-resolved citations and server-calculated confidence. |
| Low relevance | Generation is skipped and insufficient context is returned without citations. |
| Fabricated citation | Response is rejected as malformed dependency output. |
| Missing/corrupt index | Readiness fails and query returns `INDEX_NOT_READY`. |
| AI-Mode unavailable/timeout | Explicit retryable dependency error; no success-shaped fallback. |
| CI | Unit and API tests run without Ollama, downloaded models, or live host services. |

## 6. Risks and mitigations

| Risk | Impact | Mitigation |
| --- | --- | --- |
| RAG is accidentally containerized | Violates the Release 1 assessment. | Provide host commands only and assert no RAG Dockerfile or Compose service. |
| RAG bypasses AI-Mode | Duplicated provider policy and architecture violation. | Keep all Ollama access in AI-Mode and test the injected HTTP boundary. |
| Broad ingestion exposes secrets or personal data | Privacy or security failure. | Use an explicit manifest, repository-contained paths, extension/segment deny rules, and no remote ingestion API. |
| Failed rebuild destroys a usable index | Local service outage. | Build a temporary SQLite index and replace the active file only after success. |
| Embedding model or dimensions change | Invalid similarity results. | Store model and dimension metadata and reject incompatible indexes/responses. |
| Retrieval score is treated as certainty | Unsupported confident answer. | Calibrate thresholds and require valid citation coverage. |
| Indexed prompt injection changes behavior | Unsafe or unsupported answer. | Delimit chunks as untrusted data, constrain output schema, and validate citation IDs. |
| Local model is slow | Demo timeout. | Bound chunks, batches, context, and answer size; warm approved models before evidence capture. |
| One PR is difficult to review | Defects become harder to isolate. | Keep focused commits for embedding, service/index, query, and docs/tests. |

## 7. Evidence checklist

- [ ] Pull request closing #122-#125 with focused commits.
- [ ] AI-Mode and RAG lint, format, compile, and test output.
- [ ] Host versions and startup commands.
- [ ] Successful index summary with source/chunk counts and model dimension.
- [ ] Grounded query with citations and confidence.
- [ ] Insufficient-context query showing generation was skipped.
- [ ] Missing-index and unavailable-AI-Mode behavior.
- [ ] Confirmation that RAG is absent from Docker Compose.
- [ ] Sanitized screenshots or terminal output for the report and video.
- [ ] Known limitations and individual contribution links.
