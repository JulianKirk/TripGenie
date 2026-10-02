# Student 1 Release 1 contribution log

Contributor: Aaditya Rai (GitHub `aadirai31`). Verified 2 October 2026 with
`gh pr view <n>` and `git log --author=aadi origin/main`. Only pull requests
authored by `aadirai31` are listed. Pull requests are squash-merged, so each
has one commit on `main`; the branch commits are listed for traceability.

## Merged

| Merged (UTC) | Pull request | Issues | Commit on `main` | Branch commits | Contribution |
| --- | --- | --- | --- | --- | --- |
| 23 Sep 06:04 | [#134 Define Release 1 shared RAG architecture and contracts](https://github.com/JulianKirk/TripGenie/pull/134) | #121 | [`c8662b3`](https://github.com/JulianKirk/TripGenie/commit/c8662b31c041092d449d456f614e936eba7f5d8e) | `f512f7c`, `905bd70` | Shared RAG architecture, HTTP/embedding contract, delivery plan, flow diagrams. |
| 28 Sep 08:55 | [#135 Implement the shared non-containerized RAG service](https://github.com/JulianKirk/TripGenie/pull/135) | #122-#125 | [`9effd75`](https://github.com/JulianKirk/TripGenie/commit/9effd75837d76c9a59ad219c407d56f3869205f7) | `535a29b`, `57a0c56` | AI-Mode `/embed` gateway; host RAG service: manifest ingestion, SQLite vector index, feature-scoped retrieval, grounded generation, citation validation, confidence, insufficient context, tests. |
| 29 Sep 20:53 | [#143 Run AI-Mode on the host and connect Compose backends to host AI, MCP and RAG](https://github.com/JulianKirk/TripGenie/pull/143) | #129 | [`d2d7803`](https://github.com/JulianKirk/TripGenie/commit/d2d78033c53079b149960d68c8744d2184b2f38b) | `3ad0806` | Removed AI-Mode from Compose, `host.docker.internal` wiring for all backends, local host services runbook. |
| 29 Sep 21:29 | [#144 Student 1 RAG query and MCP options routes](https://github.com/JulianKirk/TripGenie/pull/144) | #127 | [`e7edcff`](https://github.com/JulianKirk/TripGenie/commit/e7edcfffcc479fe0fc28d3a65c6b8e2d5f7e55f8) | `f9ec4c4`, `1598cee`, `c6e156b`, `92dc84b`, `9f0df7b` | Backend `rag-query` and `mcp-options` routes, travel knowledge sources, RAG fix to honour the model's insufficient-context verdict and threshold calibration (0.5/0.7/0.8) from measured scores. |
| 1 Oct 03:03 | [#147 Fix Release 0 AI suggestions: grammar-safe Ollama schemas and AI-Mode error parsing](https://github.com/JulianKirk/TripGenie/pull/147) | - | [`71fb4d7`](https://github.com/JulianKirk/TripGenie/commit/71fb4d710abe51b15e1e01a7496b18d9f823dd67) | `d288e1a`, `1e15c74` | Fixed a Release 0 regression found during Release 1 testing: Ollama grammar rejected output schemas, and Student 1 mis-parsed AI-Mode error bodies carrying a tool trace. |
| 1 Oct 03:34 | [#145 Student 1 frontend RAG and MCP panels](https://github.com/JulianKirk/TripGenie/pull/145) | #128 | [`aec615c`](https://github.com/JulianKirk/TripGenie/commit/aec615cf388ae13bb51567cd00186b021a85516e) | `dddfff5`, `c20bf9c`, `eb5e9ce`, `fad78e7`, `b721561` | Knowledge-base and trip-options panels, long client timeouts for local models, focus management on swapped results. |

## Open or in progress

| Item | State | Commit | Contribution |
| --- | --- | --- | --- |
| [PR #159 Student 1 CI with MCP and RAG disabled](https://github.com/JulianKirk/TripGenie/pull/159) (#130) | Open | `c1ff13d` ([run 36957328723](https://github.com/JulianKirk/TripGenie/actions/runs/36957328723) green) | Student 1 CI runs RAG server tests and a Compose readiness job with MCP/RAG disabled and asserts no host-only service in Compose. |
| Issue [#132](https://github.com/JulianKirk/TripGenie/issues/132) evidence (this branch, `aadirai31/issue-132-release-1-evidence`) | Not yet pushed | Commit referencing #132 | Release 1 evidence capture, register, contribution log, report section, demo runbook. |

## Ownership boundaries

- **Student 1 feature:** Trip & Itinerary backend/frontend RAG and MCP integration (#144, #145) and Release 0 regression fix (#147).
- **Shared RAG server:** designed and implemented by Aaditya (#134, #135); later shared fixes by teammates (for example [#150](https://github.com/JulianKirk/TripGenie/pull/150), tool-free AI-Mode generation for RAG, by JulianKirk) are not claimed here.
- **Not claimed:** the MCP server and tool catalogue, other students' RAG/MCP integrations, and the agentic loop ([#141](https://github.com/JulianKirk/TripGenie/pull/141), by `jeffery-jefferson`).
