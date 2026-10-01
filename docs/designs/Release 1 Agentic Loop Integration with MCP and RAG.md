
## Loop design

Each mode follows the lab pattern: a **collector** gathers evidence (OBSERVE), the two Claude agents review it (implementation, then review), and the output is saved for the report. Only the collector's checks decide pass/fail. Claude is used by the loop and CI only; AI-Mode and RAG generation stay on Ollama with the approved models.

| Mode                             | OBSERVE (what the collector does)                                                                                                                                               |
|----------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `services` (Release 0, existing) | Runs `checks/*.json` against a running backend.                                                                                                                                 |
| `mcp`                            | Connects to the MCP server on port 8012, lists the tools, calls one valid read per student, and confirms invalid input returns `VALIDATION_ERROR`.                              |
| `rag`                            | Sends an answerable query (expect citations + confidence category) and an unanswerable one (expect insufficient-context) to port 8011, using `config/calibration-queries.json`. |
| `ci`                             | Fetches the latest `student-x-ci.yml` runs and their artifacts (see below).                                                                                                     |

Unlike Labs 7 and 8, which mostly check that files exist, the MCP and RAG collectors call the running servers.

## Mode selection

`agentic_loop.py` gets a `--mode {services,mcp,rag,ci}` flag. When no flag is given and it's run in a terminal, it shows a menu like the labs:

```text
AGENTIC LOOP
  1 - Services
  2 - MCP
  3 - RAG
  4 - CI
  0 - Exit
Choose a validation mode:
```

`--ci` (non-interactive) skips the menu and the human review and defaults to `services`.

## Fetching CI results automatically

Lab 5 downloads the CI artifact by hand. The `ci` mode does it with the `gh` CLI:

```bash
gh run list --workflow student-1-ci.yml --branch <branch> --limit 1 --json databaseId,conclusion,headSha
gh run download <run-id> --dir reports/ci/student-1
```

The collector turns each run's conclusion and artifacts into evidence for the agents. It uses the developer's `gh auth login`. If `gh` is unavailable, the mode reports that instead of failing the other modes.

## Local only

The agentic loop runs on the developer's machine, not in GitHub Actions; the former `agentic-ci.yml` workflow has been removed. Every mode needs things CI does not have or should not need: the integrated services, the host MCP and RAG servers, Ollama with the approved models, and Claude credentials. Student CI workflows keep MCP and RAG disabled, so a student build never needs a model.

Services mode can still validate several services in one run: `SERVICES="student-1 student-3" python agentic_loop.py --ci --mode services` iterates those entries in `services.json`, waits for each to become ready, runs its `checks/*.json`, and marks the rest skipped. A service that doesn't become ready is reported as failed in its own section; the rest still run. The result is one report with a section per service and one implementation-agent and review-agent pass over the combined evidence, saved under `reports/`.

## Testing with the Agentic Loop

During OBSERVE the loop runs the checks below against the running servers. Each check passes or fails; the implementation and review agents then comment on the results. Unit tests use fakes, so these live checks are what show the assembled system works.

### MCP

The loop checks that:

- **Registered tools:** listing the tools returns all 16.
- **Structured results:** one valid call per student returns `ok: true`, a `data` payload, and the matching `source`.
- **Correct data:** the IDs and amounts in a tool result match the same backend endpoint called directly.
- **Tool boundaries:** invalid input (e.g. `limit: 0`, a malformed ID) returns `VALIDATION_ERROR`, and an unknown tool name is rejected.
- **Consistency:** repeating the same call returns the same result.
- **Latency:** each call completes in under 3 seconds.
- **Tool selection (optional):** given a plain-English request, the implementation agent picks a tool, and the loop checks it matches the expected tool.

### RAG

The loop uses the cases in `ai-services/rag-server/config/calibration-queries.json` and checks that:

- **Grounded answers:** each answerable question returns an answer, a confidence category, and citations that include its `expected_source_ids`.
- **Insufficient context:** the unanswerable question returns the insufficient-context response.
- **Consistency:** repeating a question returns the same citations and confidence category. The answer wording can vary, since it comes from the model.
- **Latency:** the insufficient-context response returns in under 3 seconds, because it skips generation; a full answer returns in under 30 seconds.
