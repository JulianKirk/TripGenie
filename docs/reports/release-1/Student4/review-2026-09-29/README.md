# Detailed code and functional review — 29 September 2026

Reviewed application commit `b38273d` against base `9effd758`. The working tree was
clean and `git push origin Student4/AddActivitiesServiceMcp` confirmed everything
was already pushed before review. This follow-up records review evidence; it does
not change application behavior or resolve the findings below.

**Assessment: usable for manual testing, but fix the five P2 findings before merge.**
No critical security or data-loss defect was found in the inspected changes.
Passing tests do not establish natural-language correctness.

## Code review findings

### 1. P2 — A whole-group budget can be interpreted as listed price

[assistant_constraints.py:112–116](../../../../../student-4/backend/student4_backend_service/assistant_constraints.py)
recognizes `total`, `altogether`, and `entire party/group`, but not `whole group`.
The explicit request “Find an activity in Sydney for 4 people under AUD 100 for
the whole group” is therefore enforced as a listed-price ceiling. Live output
approved cards with party totals AUD 120 and AUD 180, alongside the valid AUD 88
option. The deterministic fixture likewise approves AUD 45 × 4 = AUD 180.

Recognize the expressed party basis or ask for clarification; do not silently
reinterpret it as a listed-price budget. Add equivalent-wording regressions.

### 2. P2 — Automatic fallback cards can reverse a correct rejection

[assistant_final.py:56–57 and 75–81](../../../../../student-4/backend/student4_backend_service/assistant_final.py)
restores eligible IDs when the final answer contains no references, then removes
the model's explanation. Eligibility checks cover numeric/date/accessibility facts,
but not every semantic requirement, including location.

In a deterministic endpoint reproduction, a Melbourne request gets a Sydney search
result; the model correctly says the inspected activity is in Sydney and unsuitable.
The backend replaces that rejection with a checked-price summary and the Sydney
card. Separately, live “Find activities in Sydney for no less than AUD 30” returned
both Sydney and Melbourne cards. The live result alone does not prove which model
final branch executed; the injected-transport reproduction isolates the fallback bug.

Preserve an explicit no-suitable-candidates outcome. Do not automatically select
records unless all material constraints have been checked independently.

### 3. P2 — The no-read budget guard removes useful clarification

[assistant_final.py:83–91](../../../../../student-4/backend/student4_backend_service/assistant_final.py)
replaces every price-constrained final answer without activity reads. This includes
nonfactual clarification questions and refusals, not just ungrounded claims.

For “Find nearby activities under AUD 100”, a deterministic model response of
“Which city or area would you like to explore?” becomes “I cannot verify activity
recommendations against this budget because no activity data was requested.” The
user loses the question needed to proceed. Distinguish clarification/refusal from
recommendation outcomes before suppressing prose.

The separate live nearby request instead searched without a location and returned
cards in multiple cities. That is another manifestation of semantic unreliability,
not evidence that the specific clarification branch executed live.

### 4. P2 — A date-shaped input can silently lose its schedule requirement

[assistant_constraints.py:203–206](../../../../../student-4/backend/student4_backend_service/assistant_constraints.py)
extracts only zero-padded ISO dates. `2026-10-1` is neither accepted nor rejected;
it leaves the request unconstrained. Search reconciliation then removes any date
the model supplied. In the deterministic endpoint reproduction, even a correctly
normalized `2026-10-01` tool argument is stripped.

Live “Find an activity in Sydney on 2026-10-1” claimed availability and returned
Friday, Saturday and Sunday activities for the requested Thursday. Limited grammar
is reasonable, but unsupported date-shaped inputs must clarify or normalize rather
than silently broaden the search.

### 5. P2 — Card controls do nothing with JavaScript disabled

[assistant_results.html:19–20](../../../../../student-4/frontend/student4_frontend_service/templates/partials/assistant_results.html)
uses button elements with only `hx-get` behavior. Ordinary form submission does
render the assistant answer and cards without JavaScript, but **View details** and
**Add to itinerary** send no request and open no page/dialog. Confirmed in Chromium
with JavaScript disabled, not merely inferred from HTML.

Provide normal links/forms with full-page responses and retain HTMX enhancement.
The current test only checks the full-page wrapper and dialog target, missing the
inactive actions.

## Scope, strengths and non-blocking observations

Independent reviewers inspected backend orchestration/constraints, MCP/AI-Mode,
and frontend/search changes. The coordinating review inspected Compose, CI and host
configuration. Existing Graphify output was consulted for navigation; it predates
these MCP changes, so source, contracts and tests were authoritative.

Read-only tool allowlisting, selected-trip scope, actual execution traces,
request-local activity provenance and fresh card reads were sound within the
inspected scope. Frontend output is escaped and calls only its own backend. MCP
writes use public APIs, do not retry uncertain outcomes, and preserve explicit
confirmation for deletion. AI-Mode retains optional-system compatibility and
combined prompt limits. Catalogue variants are narrow and SQL-escaped.

Non-blocking observations:

- SDK-invalid arguments produce valid MCP text-only `isError` responses before the
  structured envelope wrapper. The current assistant handles these; the MCP README's
  universal failure-envelope claim should be qualified.
- MCP activity-read validation is partial: malformed provider fields beyond IDs,
  price and pricing basis can pass. This permissiveness predates this branch, while
  the application assistant separately validates Activity models. Strengthening the
  shared read boundary is useful future work for external clients.
- Update advertises idempotency although replacement changes schedule UUIDs. No
  consumer breakage was established; clarify the intended semantic guarantee.
- No-read date/accessibility prose remains advisory, as documented previously.

Separate RAG UI and validation-loop feature completeness are not judged here. Other
student feature UIs and arbitrary user datasets were not functionally exercised.

## Automated verification

All **568 tests passed** across Student 4, MCP and AI-Mode on this checkout;
`tests.txt` contains the output and existing Pydantic-settings warning. Reviewers
also ran scoped suites (113 backend assistant tests, 90 MCP tests, 40 AI-Mode tests,
frontend/repository tests and public/database keyword contract tests). These are
not additional distinct tests to add to 568.

`reproduce_findings.py` invokes the actual assistant HTTP endpoint via the existing
protocol/model fakes. `deterministic-findings.json` captures all four backend
findings. Run it with `.venv/bin/python` from a development installation; it does not
mutate the catalogue or use live inference. These are review reproductions, not
passing regression assertions that endorse the faulty behavior.

## Functional review

Host AI-Mode/MCP processes from the prior session were no longer running. They were
restarted as transient user services; Ollama and the isolated `tripgeniefunctest`
Compose application were already running. Real Llama 3.1 8B was used.

| Check | Result / evidence |
| --- | --- |
| Full external MCP CRUD | Pass: create, get, filtered search, update, delete, not-found; `mcp-crud.json` |
| Trip context / itinerary / committed cost | Pass: temporary trip, empty itinerary, AUD 0 cost via real MCP |
| Standard AUD 100 party budget | Pass: 4 participants, garden card, verified AUD 88 total |
| Sunday date plus party budget | Pass: matching Sunday schedule and AUD 88 total |
| Conflicting price limits | Pass: clarification without MCP calls |
| Categories | Pass: successful actual MCP category tool |
| Delete request from frontend agent | Pass: refusal, no tool calls, no catalogue changes |
| Kayaking wording | Pass: real Sydney kayak card |
| Whole-group budget phrasing | Fail: over-budget AUD 120/AUD 180 cards |
| Unpadded date | Fail: wrong-weekday cards presented as available |
| Sydney minimum-price request | Fail: a Melbourne card also returned |
| Nearby request without location | Fail: cards returned rather than asking for location |
| Normal browser | Pass: loading state, card, actual trace, details, Add then Remove, no page errors |
| Mobile 390px | Pass: no horizontal overflow for the tested budget response |
| JavaScript-disabled form | Submission/cards pass; both card actions fail |
| MCP outage | Pass: clear unavailable response, ordinary catalogue still visible, no direct-search fallback |
| MCP recovery | Pass: actual category call after restart; `readiness.json` |

`assistant-live.json` and `cases.json` contain the nine primary requests/results;
`nearby-clarification.json` is the separate live nearby result. They are targeted
review cases selected to probe defects, not a blind accuracy benchmark. The reused
runner only knows some old case names: its automatic aggregate score is not used
for this review. Screenshots and browser assertions are stored beside this report.
The temporary CRUD activity and trip were deleted. All 14 catalogue records match
the before-test snapshot exactly.

## Manual testing

Open **http://localhost:8084/** on this machine. The backend and frontend readiness
checks pass, and the host background units `tripgenie-review-ai.service` and
`tripgenie-review-mcp.service` are active. They keep running after this review.
They are transient user services, not an installed boot-time deployment.

Useful independent prompts:

1. `Find an activity in Sydney for 4 adults with a total budget of 100 AUD.`
2. `Show a kayaking activity in Sydney.`
3. `Find an activity in Sydney for 4 adults with a total budget of AUD 100 on 2026-10-11.`
4. `Find an activity in Sydney for 4 people under AUD 100 for the whole group.` — known budget failure.
5. `Find an activity in Sydney on 2026-10-1.` — known date failure.

Expand **Tools used**, open a card, and use **Add to itinerary** if you have a trip.
Each question is independent; no chat history is retained. To stop only the new host
processes after testing: `systemctl --user stop tripgenie-review-ai tripgenie-review-mcp`.
