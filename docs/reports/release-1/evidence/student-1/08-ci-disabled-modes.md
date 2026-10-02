# CI with MCP and RAG disabled

Verified 2026-10-02 (UTC) with `gh run view 36957328723` and `gh run view 36957328723 --log --job 110683101519`.

| Field | Value |
| --- | --- |
| Workflow | Student 1 CI (`.github/workflows/student-1-ci.yml`) |
| Run | [36957328723](https://github.com/JulianKirk/TripGenie/actions/runs/36957328723), event `push`, conclusion `success` |
| Branch / commit | `aadirai31/issue-130-ci-mcp-rag-disabled` at [`c1ff13d`](https://github.com/JulianKirk/TripGenie/commit/c1ff13d97a80faf3765bce6c3fc555808fd35d7a) |
| Merge state | **Not yet on main**: [PR #159](https://github.com/JulianKirk/TripGenie/pull/159) (closes #130) is open. Re-verify on the merge commit once merged. |

## Jobs (all passed)

| Job | Result |
| --- | --- |
| Build and Validate Student 1 Database | success |
| Build and Validate Student 1 Backend | success |
| Build and Validate Student 1 Frontend | success |
| Validate Shared RAG Server | success (Ruff "All checks passed!", pytest "41 passed") |
| [Validate Student 1 Compose Readiness](https://github.com/JulianKirk/TripGenie/actions/runs/36957328723/job/110683101519) | success |

## Disabled-mode log lines (Compose Readiness job)

Step "Reject host-only AI services in Compose" (job env `STUDENT1_BACKEND_RAG_ENABLED: false`, `STUDENT1_BACKEND_MCP_ENABLED: false`):

```
No host-only AI service is defined in Compose.
```

Step "Verify MCP and RAG are disabled":

```
STUDENT1_BACKEND_RAG_ENABLED=false
STUDENT1_BACKEND_MCP_ENABLED=false
backend rag-query: HTTP 503 RAG_DISABLED
backend mcp-options: HTTP 503 MCP_DISABLED
```

## Notes

- AI-Mode has no CI enable flag: Compose sets the backend's AI-Mode URL to the
  host, and nothing in CI calls it. Ollama, AI-Mode, MCP and RAG are not
  started in CI; RAG server tests use fake transports and vectors.
- Expected: CI succeeds with runtime MCP/RAG disabled and the disabled routes
  return explicit `503` codes. Actual: as expected. Status: **Pass (branch run,
  pending merge)**.
