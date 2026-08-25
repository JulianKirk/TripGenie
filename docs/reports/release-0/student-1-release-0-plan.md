# Student 1 Release 0 Scope, Assessed Workflow, and Evidence Plan

Related architecture: [Student 1 Release 0 architecture, runtime modes, and decision traceability](../../architecture/student-1-release-0-architecture.md)
Related ADRs: [ADR-0001](../../architecture/decisions/0001-student-1-service-mapping.md), [ADR-0002](../../architecture/decisions/0002-student-1-internal-api-and-observability.md)

## 1. Documentation stance

This update uses three labels consistently:

- **Assignment / Group 07 requirement** - scope already carried by this repository and PR #17.
- **Lab pattern/example** - a visible example from `Georges034302/asd-labs`.
- **TripGenie decision** - a project-specific choice or proposal, recorded in an ADR when it should persist.

Because the assignment handout is not committed in this repository snapshot, the traceability table below points the **Assignment / Group 07 requirement** column at the repository artefacts that currently carry that scope: README, Docker Compose, CI, and the paired Student 1 design docs.

This issue updates design/reporting documentation only. It does **not** claim that the Student 1 three-service stack, timings, or AI behaviour are already implemented or verified. The current repository still exposes a placeholder `student-1-service` in [docker-compose.yml][TG-COMPOSE]; this plan describes the Release 0 target state, not executed proof.

## 2. Course source pack used

| Source | Why it matters |
| --- | --- |
| [AI Agent Configuration Guide][CFG] | Establishes local Ollama as the baseline runtime and recommends `qwen2.5:0.5b` for implementation work plus `llama3.1:8b` for review work. |
| [Lab 01][L1] | Defines the initial assessed loop as `PLAN -> ACT -> OBSERVE -> ADAPT`, with deterministic checks, manual evidence capture, and one bounded improvement. |
| [Lab 02][L2] | Extends the loop to `PLAN -> ACT -> OBSERVE -> IMPLEMENTATION AGENT -> REVIEW AGENT -> HUMAN REVIEW -> ADAPT` and requires evidence-backed review plus human decision. |
| [Lab 03][L3] | Externalises prompt assets, adds context-aware QA, and keeps prompt/review outputs grounded in live validation evidence. |
| [Lab 04][L4] | Separates UI-mode from AI-mode, uses a three-service architecture example, introduces ADR work, and shows stage banners such as `[START]`, `[OBSERVE]`, `[PROMPTS]`, `[LLM]`, `[DONE]`. |
| [asd-labs README][ASD-README] plus visible repo tree snapshot [ASD-TREE] | README references Labs 05/06, but the visible repository snapshot used here exposes only Labs 01-04 plus the AI guide and README, so later-lab requirements are treated as unavailable rather than inferred. |

## 3. Traceability summary

| Topic | Assignment / Group 07 requirement | Visible lab pattern/example | TripGenie Student 1 decision |
| --- | --- | --- | --- |
| Service decomposition | Student 1 Release 0 stays inside a three-service, independently containerised slice with local Ollama, shared home page navigation, Docker Compose, and CI continuity [TG-README][TG-COMPOSE][TG-CI]. | Lab 04 uses `frontend-service`, `enrolment-service`, and `database-service` as the microservice example [L4]. | Map that pattern onto Group 07's shared home page plus Student 1 frontend/backend/database target services; record naming and ports in [ADR-0001](../../architecture/decisions/0001-student-1-service-mapping.md). |
| CRUD and database ownership | Student 1 owns trip and itinerary CRUD while keeping one service as the only SQLite owner [TG-ARCH]. | Labs 01-04 keep SQLite ownership local to the data layer and use HTTP between services in Lab 04 [L1][L4]. | Student 1 database API remains the only SQLite owner; frontend and backend use HTTP instead of shared file access. |
| Local Ollama baseline | Release 0 keeps Ollama local and out of Release 1/2 features [TG-ARCH]. | The AI guide and Labs 01-04 use local Ollama throughout [CFG][L1][L2][L3][L4]. | Treat `qwen2.5:0.5b` and `llama3.1:8b` as subject baselines/recommendations, not mandatory runtime claims; keep `deepseek-r1:8b` out of Release 0 because it is presented as later-lab reasoning support [CFG]. |
| Assessed loop | Student 1 documentation must support the course-assessed evidence/review loop for reports and demos [TG-ARCH]. | Labs 01-04 define the loop as development/review work with evidence, prompts, human decision, rerun, and adaptation [L1][L2][L3][L4]. | Treat the assessed loop as the Student 1 development-and-validation workflow, not as the end-user itinerary suggestion runtime. |
| UI-mode vs AI-mode | Student 1 still needs a clear runtime story for CRUD flows and Ollama-assisted suggestions [TG-ARCH]. | Lab 04 separates Normal UI from AI Mode in the frontend and backend routes [L4]. | Keep runtime CRUD in UI-mode and bounded suggestions in AI-mode, while documenting both separately from the assessed loop. |
| Prompt assets and review roles | Release 0 reporting must explain how prompts, evidence, and review outputs are retained [TG-ARCH]. | Lab 03 externalises prompt files; Labs 02-04 split implementation and review roles [L2][L3][L4]. | Keep prompt assets versioned and separate from service code or report prose; record which prompt text and model pair produced each review outcome. |
| Later-lab scope | Release 0 excludes MCP, RAG, multi-agent runtime, and unverified showcase requirements [TG-ARCH]. | The visible snapshot does not expose Labs 05/06 content even though README lists them [ASD-README][ASD-TREE]. | Do not invent CI/showcase requirements from hidden later labs; keep Release 0 limited to what is visible and already agreed in Group 07 scope. |
| Internal API / observability detail | Student 1 may still want health checks, internal routes, or richer logs for implementation [TG-ARCH]. | Visible labs require evidence and stage banners, but do not visibly mandate `/internal/*`, `/ready`, fixed retry counts, or exact log schemas [L1][L2][L3][L4]. | Treat `/internal/*`, `/health`, `/ready`, run IDs, correlation IDs, retry caps, and exact log schemas as TripGenie proposals only, tracked in [ADR-0002](../../architecture/decisions/0002-student-1-internal-api-and-observability.md). |

## 4. Release 0 scope

### In scope

- Trip CRUD and itinerary-item CRUD design for Student 1.
- Filtering itinerary items by trip and date/category.
- A local Ollama-assisted **draft suggestion** capability that stays inside Student 1 and requires human approval before persistence.
- Documentation of a three-container Student 1 target architecture that preserves the Group 07 shared home page pattern.
- Evidence-backed report guidance for prompts, live validation, review output, human decision, and rerun/adaptation.

### Explicitly out of scope

- Auto-persisted AI decisions or autonomous product behaviour presented as the assessed course loop.
- Release 1 MCP/RAG features and Release 2 multi-agent/cloud features.
- Invented Labs 05/06 requirements.
- Claims that proposed endpoints, timings, or observability conventions already work without execution evidence.

## 5. The assessed Student 1 workflow

The course-assessed loop is a **software development and review workflow**.

- **Lab 01** establishes `PLAN -> ACT -> OBSERVE -> ADAPT` around deterministic validation and one improvement [L1].
- **Lab 02** adds implementation agent, review agent, and explicit human decision [L2].
- **Lab 03** moves prompt text into files and keeps outputs tied to live evidence [L3].
- **Lab 04** applies the same evidence discipline to architecture work, ADRs, and UI-mode/AI-mode separation [L4].

For Student 1 Release 0, the concrete assessed workflow should be documented and demonstrated like this:

| Step | Student 1 activity | Evidence to retain in the report |
| --- | --- | --- |
| Plan | Define the bounded goal for the current slice or change: scope, endpoint(s), data rules, pass condition, and any NFR being checked. | The written goal, success criteria, and explicit scope boundary. |
| Act + Observe | Run the relevant app/services, inspect the database or seed data, and execute browser plus `curl` checks. Capture expected/actual/pass-fail results and any timing evidence. | DB observations, browser results, `curl` outputs, Expected/Actual/Pass-Fail table rows, and NFR timings where applicable. |
| Implementation agent | Feed the live evidence into the implementation prompt. The course baseline is local Ollama with `qwen2.5:0.5b` for implementation-oriented advice [CFG][L2][L3]. | Prompt asset used, model name, and the exact implementation recommendation returned. |
| Review agent | Review the implementation recommendation using the same evidence. The course baseline review model is `llama3.1:8b` [CFG][L2][L3]. | Prompt asset used, model name, and the three-line `Risk / Correction / Retest` output or equivalent evidence-backed review note. |
| Human review | Accept, partially accept, or reject the AI recommendation based on the evidence. | Human decision, short rationale, and any scope correction. |
| Adapt + rerun | Apply one bounded improvement, rerun the relevant checks, and compare before/after results. | What changed, which checks were rerun, before/after evidence, and the final outcome. |

## 6. Prompt assets and report evidence to retain

Student 1 documentation should explicitly retain or reference:

1. the prompt assets or prompt excerpts used for implementation/review;
2. the live evidence that informed them;
3. the implementation-agent output;
4. the review-agent output;
5. the human decision; and
6. the rerun/retest evidence after adaptation.

At minimum, the report evidence pack should include:

- a short PLAN statement and stop condition;
- manual browser and `curl` checks recorded as **Expected / Actual / Pass-Fail**;
- database evidence showing the relevant Student 1 state or schema assumptions;
- the NFR timing proof when a timing requirement is claimed;
- prompt file/path references for implementation, review, and any context-aware runtime prompt assets;
- ADR links for any long-lived TripGenie-specific deviations from the visible labs.

**Important:** the visible course prompts repeatedly warn against inventing new services, APIs, database fields, or requirements [L1][L2][L3][L4]. Student 1 report text should therefore label every claim as either an assignment requirement, a visible lab example, or a TripGenie project decision.

## 7. Runtime AI-mode is separate from the assessed loop

The bounded TripGenie itinerary-suggestion flow can remain in Release 0, but it is a **runtime design** rather than the course-assessed loop.

| Concern | Assessed course loop | TripGenie runtime AI-mode |
| --- | --- | --- |
| Trigger | Student/team validates or improves the system. | A user requests itinerary help for a specific trip/day. |
| Main evidence | DB checks, browser checks, `curl`, timing evidence, prompt outputs, and human review. | Current trip/itinerary context, prompt assets, and model output returned to the user. |
| Decision point | Human decides whether to accept, partially accept, or reject a recommended change. | Human user reviews/edit suggestions before any persistence. |
| Persistence | Adaptation changes docs/code, then reruns evidence checks. | Suggestions remain drafts until the user saves them through normal CRUD. |

That distinction replaces the earlier wording that treated the runtime suggestion flow itself as `PLAN -> ACT -> OBSERVE -> ADAPT`.

## 8. Limitations and open points

- [asd-labs README][ASD-README] advertises Labs 05/06, but the visible repository snapshot used for this update exposes only Labs 01-04 plus the AI guide and README [ASD-TREE]. No later-lab requirement is asserted here.
- Current Group 07 repository evidence still shows a placeholder Student 1 service in [docker-compose.yml][TG-COMPOSE]; service names, ports, internal API paths, and observability details remain proposed until implemented.
- `deepseek-r1:8b` appears in the AI guide only as a reasoning model for later labs [CFG], so it is intentionally kept out of Student 1 Release 0 scope.

[TG-ARCH]: ../../architecture/student-1-release-0-architecture.md
[TG-README]: ../../../README.md
[TG-COMPOSE]: ../../../docker-compose.yml
[TG-CI]: ../../../.github/workflows/student-1-ci.yml
[CFG]: https://github.com/Georges034302/asd-labs/blob/4777809f17f5e2ec681d6b727dc79acb0f55fc1d/AI_Agent_Configuration_Guide.md
[L1]: https://github.com/Georges034302/asd-labs/blob/4777809f17f5e2ec681d6b727dc79acb0f55fc1d/Lab_01_DevOps_and_Agentic_AI_Foundations.md
[L2]: https://github.com/Georges034302/asd-labs/blob/4777809f17f5e2ec681d6b727dc79acb0f55fc1d/Lab_02_Environment_and_Multi_Model_Workflows.md
[L3]: https://github.com/Georges034302/asd-labs/blob/4777809f17f5e2ec681d6b727dc79acb0f55fc1d/Lab_03_Prompting_Specs_and_Context_Execution.md
[L4]: https://github.com/Georges034302/asd-labs/blob/4777809f17f5e2ec681d6b727dc79acb0f55fc1d/Lab_04_Architecture_and_Agentic_Design_Patterns.md
[ASD-README]: https://github.com/Georges034302/asd-labs/blob/4777809f17f5e2ec681d6b727dc79acb0f55fc1d/README.md
[ASD-TREE]: https://github.com/Georges034302/asd-labs/tree/4777809f17f5e2ec681d6b727dc79acb0f55fc1d
