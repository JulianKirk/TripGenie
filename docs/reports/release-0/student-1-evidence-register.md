# Student 1 Release 0 evidence register

Prepared: **4 September 2026 (AEST)**

Related issue: [#15 – Prepare Release 0 evidence, report contributions, and demo](https://github.com/JulianKirk/TripGenie/issues/15)

This register separates verifiable repository evidence from evidence that still
requires a real local or showcase execution. A link to implementation is not
treated as proof that the application was executed.

## 1. Verified repository and GitHub evidence

| Evidence item | Status | Verified source | What it proves | What it does not prove |
| --- | --- | --- | --- | --- |
| Student 1 planning and architecture | Verified | [PR #17](https://github.com/JulianKirk/TripGenie/pull/17), [architecture](../../architecture/student-1-release-0-architecture.md), [ADR-0001](../../architecture/decisions/0001-student-1-service-mapping.md), [ADR-0002](../../architecture/decisions/0002-student-1-internal-api-and-observability.md) | Student 1 Release 0 scope, service boundaries, and recorded decisions exist in repository history. | Runtime operation. |
| Database microservice | Verified source only | [PR #18](https://github.com/JulianKirk/TripGenie/pull/18), [`student-1/database`](../../../student-1/database) | The database API implementation and SQLite ownership were merged. | A local database process, current row counts, or browser CRUD. |
| Backend CRUD API | Verified source only | [PR #21](https://github.com/JulianKirk/TripGenie/pull/21), [`student-1/backend`](../../../student-1/backend) | The Student 1 public API implementation was merged. | An integrated local request. |
| HTMX frontend | Verified source only | [PR #22](https://github.com/JulianKirk/TripGenie/pull/22), [`student-1/frontend`](../../../student-1/frontend) | The Student 1 frontend implementation was merged. | A rendered browser session or full CRUD demonstration. |
| Shared AI-Mode and Student 1 draft suggestions | Verified source only | [PR #23](https://github.com/JulianKirk/TripGenie/pull/23), [runtime notes](../../architecture/student-1-runtime-ai-mode.md), [runtime prompt](../../../student-1/backend/backend_service/prompts/runtime_ai_suggestions_v1.md) | The bounded draft-suggestion path, prompt asset, and shared AI-Mode integration were merged. | Live Ollama availability, response quality, or a successful model request. |
| Student 1 Compose topology | Verified source only | [PR #29](https://github.com/JulianKirk/TripGenie/pull/29), [`docker-compose.yml`](../../../docker-compose.yml) | Student 1 frontend, backend, database, and shared AI-Mode are configured in the shared Compose topology. | `docker compose up`, healthy containers, CRUD, or Ollama execution on a team machine. |
| Student 1 CI | Verified | [Run 33764177551](https://github.com/JulianKirk/TripGenie/actions/runs/33764177551) on merge commit [`52fc537d`](https://github.com/JulianKirk/TripGenie/commit/52fc537d6470afa5f2f2b2ba26c1277d10a6fe74) | The run completed successfully. Its [database](https://github.com/JulianKirk/TripGenie/actions/runs/33764177551/job/100677683069), [backend](https://github.com/JulianKirk/TripGenie/actions/runs/33764177551/job/100677682913), and [frontend](https://github.com/JulianKirk/TripGenie/actions/runs/33764177551/job/100677682665) jobs ran syntax checks, Ruff, pytest, and image builds. | Integrated Compose startup or live Ollama use. |
| Shared AI-Mode CI | Verified | [Run 33764177488](https://github.com/JulianKirk/TripGenie/actions/runs/33764177488) on merge commit [`52fc537d`](https://github.com/JulianKirk/TripGenie/commit/52fc537d6470afa5f2f2b2ba26c1277d10a6fe74) | The [Build and Validate Shared AI-Mode](https://github.com/JulianKirk/TripGenie/actions/runs/33764177488/job/100677683568) job completed successfully with syntax, Ruff, pytest, and image-build steps. | Live Ollama/model quality or a Student 1 end-to-end AI request. |

The workflow names required by the rubric are implemented in this repository as
`student-1-ci.yml` through `student-5-ci.yml`; the `-ci` suffix is the repository
filename convention. Student 1's workflow is
[`.github/workflows/student-1-ci.yml`](../../../.github/workflows/student-1-ci.yml).

## 2. Contribution and commit links

The following claims are limited to pull requests whose GitHub author is
`aadirai31` and which GitHub records as merged.

| Merged (UTC) | Pull request | Merge commit |
| --- | --- | --- |
| 29 Aug 2026 05:32 | [#17 – Student 1 Release 0 architecture](https://github.com/JulianKirk/TripGenie/pull/17) | [`434bf2ee`](https://github.com/JulianKirk/TripGenie/commit/434bf2ee23a4c8b1f42f4bfca564c286e1ca6e16) |
| 29 Aug 2026 06:32 | [#18 – SQLite database microservice](https://github.com/JulianKirk/TripGenie/pull/18) | [`8bd249a7`](https://github.com/JulianKirk/TripGenie/commit/8bd249a745d1dfaa21683b911193b878df291de0) |
| 29 Aug 2026 07:16 | [#21 – Backend CRUD API](https://github.com/JulianKirk/TripGenie/pull/21) | [`12c4f216`](https://github.com/JulianKirk/TripGenie/commit/12c4f2160e358e1d7359f9ca270770800b129955) |
| 31 Aug 2026 01:22 | [#22 – HTMX trip and itinerary frontend](https://github.com/JulianKirk/TripGenie/pull/22) | [`6d6e8a75`](https://github.com/JulianKirk/TripGenie/commit/6d6e8a75447f2aed95ad5fbc3f670744f1f5f71b) |
| 3 Sep 2026 13:46 | [#23 – Shared Release 0 AI-Mode](https://github.com/JulianKirk/TripGenie/pull/23) | [`863bc627`](https://github.com/JulianKirk/TripGenie/commit/863bc6271248d014e9224a21c477164045d5c860) |
| 3 Sep 2026 13:58 | [#29 – Student 1 Compose topology](https://github.com/JulianKirk/TripGenie/pull/29) | [`52fc537d`](https://github.com/JulianKirk/TripGenie/commit/52fc537d6470afa5f2f2b2ba26c1277d10a6fe74) |

These links establish repository authorship and integration history only. They
do not establish the amount of work performed outside GitHub or any other
student's contribution.

## 3. Pending manual evidence

No item in this section may be marked complete without attaching the actual
dated artefact and recording the machine/environment used. Detailed capture
steps and filenames are in [the manual evidence directory](evidence/student-1/README.md).

| Required evidence | Status | Minimum qualifying capture |
| --- | --- | --- |
| Pre/post local testing | Pending manual capture | A dated Expected / Actual / Pass-Fail table with command output from the same bounded change, including the failing/baseline observation and the rerun after adaptation. |
| Compose startup | Pending manual capture | `docker compose ... up --build -d`, followed by dated `docker compose ... ps` and relevant service logs showing the integrated services running. |
| Seeded database state | Pending manual capture | API or database-API output that records actual Trip and Itinerary Item counts and representative records; do not commit the SQLite file. |
| Browser CRUD | Pending manual capture | Dated screenshots showing create, read, update, and delete through the Student 1 frontend, with enough context to identify the record and application. |
| Service health/readiness | Pending manual capture | Dated responses for the shared portal, Student 1 frontend, backend readiness, database health, and shared AI-Mode health. |
| Live AI request | Pending manual capture | A real Student 1 request using an approved model, including the model, prompt asset version, run/correlation identifiers, draft result, and human review before save. |
| Live Ollama quality | Pending manual capture | The actual model list and response; include limitations or poor output rather than replacing it with synthetic success. |
| Assessed agentic loop review record | Pending manual capture | PLAN, deterministic observations, prompt assets, implementation output, review output, human decision, adaptation, and rerun from one real execution. |
| Application screenshots | Pending manual capture | Shared portal, Student 1 list/detail/forms, and integrated result screens from the running application. |
| Group video URL | Pending manual capture | Published URL, duration at or below ten minutes, and the Student 1 segment location. |
| Showcase/video participation and attendance | Pending manual confirmation | The real recording and attendance record. Repository activity is not attendance evidence. |

## 4. Explicitly excluded evidence

[Issue #14](https://github.com/JulianKirk/TripGenie/issues/14) and
[PR #35](https://github.com/JulianKirk/TripGenie/pull/35) were closed without
merge after being judged over-scoped for Release 0. Their custom Compose smoke
framework, fake Ollama transport, and associated results are **not delivered**
and must not appear in the report as implemented evidence.

Release 0 evidence instead uses the existing Student 1 CI and AI-Mode CI runs,
the merged PR #29 Compose configuration, and real manual Compose/browser/Ollama
captures when the team performs them.
