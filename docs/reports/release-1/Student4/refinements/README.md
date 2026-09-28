# Activity assistant refinement measurements — 28 September 2026

This pass improves instruction separation and several common interactions. It does
**not** establish generally reliable recommendation reasoning. User authorization
was to experiment autonomously, measure, review, and push to the existing PR #139.

## Kept changes

- Add optional `system` to AI-Mode generation; forward it separately to Ollama with
  templating enabled. Existing callers remain compatible. Both input fields share
  the existing character limit and neither is logged.
- Student 4 puts trusted policy in `system`, and the question, tool schemas and
  observations in `prompt`, with the current question after tool context.
- Clarify read-only refusals, missing context, conflicting requirements, listed
  versus party pricing, and activity-card output. Contrasting syntax examples use
  different locations/prices from the evaluation requests to reduce copying of a
  single example's filters.
- Keep the actual MCP schemas, backend argument validation, read-only allowlist,
  selected-trip scope and discovered-ID constraints. No fallback bypasses MCP.

## Method and results

Baseline is commit `e1c3fc0`. Ten development questions were fixed before prompt
changes. The scoring rubric was written after inspecting development failures;
this is **not a blind accuracy benchmark**. All saved runs are scored consistently
by `evaluate.py`; `scores.json` contains the resulting per-case checks. Review
corrected two overly narrow rubric checks: CULTURE is a reasonable museum category,
and a clear cannot-delete refusal need not literally contain “read-only”.

| Configuration | Checks passed / 10 | Median seconds |
| --- | ---: | ---: |
| Original, Llama 3.1 8B | 5 | 3.74 |
| Original repeat, Llama 3.1 8B | 4 | 4.70 |
| System separation only | 5 | 3.29 |
| Expanded prompt | 5 | 3.31 |
| Shorter rewritten prompt | 2 | 6.26 |
| Shorter prompt + question last | 1 | 6.69 |
| Minimal edits to original prompt + question last | 4 | 3.89 |
| Simplified argument-generation schema experiment | 3 | 1.50 |
| Contrasting examples, selected version | **8** | **2.26** |
| Extra budget/conflict examples, rejected | 7 | 1.51 |
| Selected version through rebuilt public backend | **8** | **2.50** |
| Original, Qwen 2.5 7B | 7 | 3.33 |
| Selected version, Qwen 2.5 7B | 7 | 2.50 |

Do not interpret these small latency samples as a performance guarantee. The first
baseline request included warm-up effects; medians are reported rather than a
claimed speedup. Temperature was zero, but repeated results were not identical.
Qwen's aggregate score masks invented narrative details; it was not selected.

The eight passing checks cover two wheelchair/price phrasings, Melbourne museum
cards, a nonexistent exact name, category listing, write refusal, asking for a
missing location, and preventing an invented activity card. The two remaining
failures are conflicting price bounds and a four-person total budget. Some trials
silently changed constraints or added an unrelated date/accessibility filter.

The rubric checks successful tool execution, card location/price/accessibility,
unrequested filters, and required clarification/refusal behavior. The injection
check measures **absence of invented cards only**, not truthfulness of all prose.
Categories and refusals also have bounded text checks. Manual reading of full
responses remains necessary: a high score is not proof of factual narrative quality.

## Unseen questions and trip checks

Seven held-out questions were written before running the selected version, and
were not used for further tuning. Manual evaluation found five useful responses:
step-free Melbourne card, category paraphrase, booking refusal, missing-location
clarification, and zero-budget empty search. The missing-location case made an
unnecessary category call before asking, so it was not ideal. Two failed:

- Brisbane for two people under AUD 150: invented a wheelchair constraint and
  missed an available activity.
- Kayaking in Sydney: searched literal “kayaking” and missed the catalogue's
  “kayak” activity. Keyword matching is not semantic search.

A synthetic selected trip was also tested. Dates (5–7 October 2026), an empty
itinerary and committed activity cost AUD 0.00 were reported correctly, backed by
three actual MCP tools. The recommendation request returned real cards but wrongly
called Friday/Sunday activities available during this Monday–Wednesday trip. Treat
that as a **failed recommendation-quality check**, not a successful availability
validation. The trip was removed after browser testing.

The model's prose and inferred filters remain advisory. Real cards prevent invented
records, but do not prove suitability, affordability for a party, or date availability.
These issues need stronger structured constraint enforcement or a separately
validated planning design; adding more instructions alone did not reliably fix them.

## Reproduce

Run the host services and Compose slice as documented in `student-4/docs/mcp-assistant.md`.
This evaluation used the 14 seeded activities and no permanent catalogue mutations.
The host gateway was configured with:

```bash
AI_MODE_TIMEOUT_SECONDS=90 AI_MODE_DEFAULT_MODEL=llama3.1:8b \
  .venv/bin/uvicorn ai_mode_service.app:app --host 172.17.0.1 --port 8006
```

Model metadata: Ollama 0.33.2; Llama 3.1 8B Q4_K_M digest
`46e0c10c039e019119339687c3c1757cc81b9da49709a3b3924863ba87ca666e`, context 4096;
Qwen 2.5 7B Q4_K_M digest
`845dbda0ea48ed749caafd9e6037047aa19acfcfd82e704d7ca97d631a0b697e`, context 4096.
Qwen was tested using the gateway's existing environment model allowlist override;
repository model defaults/allowlists were not changed. Both models remain installed,
but the running gateway was restored to Llama.

```bash
python3 docs/reports/release-1/Student4/refinements/evaluate.py /tmp/new-results.json \
  --cases docs/reports/release-1/Student4/refinements/cases.json
python3 docs/reports/release-1/Student4/refinements/evaluate.py /tmp/new-held-out.json \
  --cases docs/reports/release-1/Student4/refinements/held-out-cases.json
# Score an existing development run without invoking any model:
python3 docs/reports/release-1/Student4/refinements/evaluate.py \
  docs/reports/release-1/Student4/refinements/final-http.json
```

The runner uses the public backend HTTP endpoint, sequential requests and a 200-second
client timeout. Do not run against personal data unless intended. A transport failure
aborts the run; an application error is saved and fails the check. It runs only when
explicitly invoked, never in CI. Held-out and trip cases require the manual checks
above and intentionally receive no automatic numeric score.

Baseline/repeat, Qwen runs, final HTTP, held-out and trip evidence use the public
backend. Intermediate prompt experiments invoked the real backend `answer` function
in process, with real HTTP AI-Mode and MCP; they did not substitute provider/tool
fakes. Rejected prompt assets are retained alongside their results. “Recency” used
the concise asset plus explicit activity-part wording and the question-last layout;
“simplified-schema” used the minimal asset and an unconstrained argument object only
at generation time, while retaining backend validation. That experiment failed and
was not incorporated. The original prompt is recoverable from `e1c3fc0`.

A startup attempt before MCP was running and an HTTP attempt before the rebuilt
backend was listening were excluded from model scores; neither measured inference.
All substantive prompt/model experiments, including failures, are retained here.

## Verification

- 466 automated tests passed across Student 4, MCP and AI-Mode; one existing
  Pydantic-settings warning. Full output: `verification.txt`.
- Ruff lint/format passed; strict mypy passed for 71 files.
- Student 4 backend and standalone AI-Mode images built; Compose configuration valid.
- Independent code review found no production-code blocker. Added null-system,
  combined-budget and sensitive-system logging coverage, and corrected the rubric.
- Browser checks and screenshots: `browser.txt`, `assistant.png`, `mobile.png`.
  These exercise loading state, two cards, actual tool trace, details dialog,
  explicit Add to itinerary/Remove, and mobile overflow on the final backend.

The app is left available at http://localhost:8084. Temporary evaluation trip data
was removed; the activity catalogue remains the original 14 records.
