# Checked activity constraints — 28 September 2026

This follow-up addresses failures measured in the [previous refinement pass](../README.md).
The shared MCP server remains a general CRUD interface. The frontend agent's backend
retains its read-only tool policy and now checks supported constraints independently
of model-authored arguments and prose.

## Implementation

- Parse explicit party size, AUD bounds, ISO dates/time windows and required
  accessibility/booking values into immutable request-local constraints. Clarify
  conflicts or unsupported forms before inference. Selected-trip dates and party
  size come from the real MCP trip tool.
- Reconcile search arguments with those constraints, then check returned records.
  Whole-party prices use exact Decimal multiplication for PER_PERSON and one charge
  for FLAT_ADMISSION. Participant limits and known accessibility facts are enforced.
- Read schedules through MCP for date-constrained candidates. A weekly or one-off
  schedule must intersect the requested dates and fit the complete activity duration
  in the local time window. This does not establish remaining booking capacity.
- Repeat checks on fresh final MCP detail reads. Replace constrained recommendation
  prose with authored verification text and party totals, so excluded cards cannot
  leave behind claims that they meet the request. Text-only final output can resolve
  up to six already eligible IDs.
- Support the conservative single-word variants kayaking/kayaks → kayak and
  walking/walks → walk in the ordinary catalogue API. External MCP clients receive
  the same behavior; multi-word phrases retain literal substring semantics.

## Live measurements

Same 14 seeded catalogue records, Llama 3.1 8B, host AI-Mode/MCP and containerised
application as the previous report. Public HTTP requests use the unchanged
[runner and rubric](../evaluate.py). No provider/model fakes are used here.

| Run | Result |
| --- | --- |
| Previous final development run | 8/10 bounded checks |
| New development run, `development.json` | 10/10 bounded checks; median 1.425 seconds |
| Final rebuilt repeat, `development-final.json` | 10/10 bounded checks; median 1.315 seconds |
| Four-person AUD 100 total | Garden activity, verified party total AUD 88; AUD 120 museum excluded |
| Conflicting prices | Authored clarification, zero MCP/model calls |
| Brisbane for two, AUD 150 total | Yoga activity, verified AUD 50; no invented wheelchair filter |
| Kayaking in Sydney | Actual kayak activity returned through the same public search contract |
| Trip facts | Correct 5–7 October dates, empty itinerary, AUD 0 committed cost |
| Trip recommendation | Friday/Sunday activities excluded from Monday–Wednesday trip |

`held-out.json` repeats all seven previously unseen questions; they are now regression
cases, not a new blind evaluation. Five returned useful grounded results (step-free,
Brisbane budget, categories, kayaking, zero-budget inspected-results answer). The two
relative-date requests now ask for an ISO date without model/tool calls. For the
booking request, that clarification is less helpful than explicitly saying booking
is unsupported; no write is attempted. The backend allowlist remains the authority.

`trip.json` includes actual detail calls for schedule checks. The empty recommendation
says only that no verified cards remained in inspected results, not that no suitable
activity exists anywhere. Unconstrained injection-test prose remains awkward despite
returning no invented card; the rubric's injection check measures card safety only.

The six extra requests in `additional-cases.json` exercise a matching Sunday,
a too-short local time window, an inclusive minimum, unsupported negation,
missing party size and a grouped amount. The initial run is preserved in
`additional-before-context-fix.json`: the minimum was parsed correctly, but a
six-row result exhausted prompt space because tool schemas were still included.
This led to a bounded final-only fallback, preserving observations and ID checks
while removing the now-unused tool definitions. Context still above the limit
returns the existing request-to-narrow error. `additional-final.json` completes all
six requests. Five meet their intended checks. The inclusive-minimum case now
correctly enforces AUD 30 and completes, but remains a **location-quality failure**:
the model omitted Sydney from its search, and the fallback presents price-eligible
records from other cities as well. This is preserved as evidence, not counted as a
successful recommendation. Location extraction/validation remains future work.

## Boundaries

The parser deliberately accepts a limited syntax; it is not a general natural-language
planner. Foreign currencies, grouped/signed amounts, ambiguous ranges and relative
weekday/date wording receive clarification. Semantic place/category/topic matching
and prose outside verified activity results still depend on the model. In particular,
date/accessibility/booking-only questions that produce no activity reads can still
receive unverified model prose; trip factual answers intentionally retain model text.
Only price-constrained no-read answers are currently suppressed explicitly. The small development corpus is
not an estimate of general accuracy, and latency samples are not performance guarantees.
Budget totals refer to each candidate activity for the party, not a combined itinerary.
Bounded search pages may miss relevant records; no exhaustive-match claim is made.

## Browser verification

`browser.txt`, `assistant.png` and `mobile.png` capture the whole-party budget through
the real UI. Assertions cover loading state, one verified AUD 88 card, actual search
and detail traces, details dialog, explicit itinerary add/remove, no browser errors,
and no horizontal overflow at 390px. The temporary trip is removed after checks.

## Reproduce

Use the local setup in the previous report, then from the repository root:

```bash
.venv/bin/python docs/reports/release-1/Student4/refinements/evaluate.py /tmp/constraints.json \
  --cases docs/reports/release-1/Student4/refinements/cases.json
.venv/bin/python docs/reports/release-1/Student4/refinements/evaluate.py /tmp/additional.json \
  --cases docs/reports/release-1/Student4/refinements/constraints/additional-cases.json
```

Trip cases require the temporary trip `trip_refinement_eval` with destination Sydney,
2026-10-05 through 2026-10-07 and traveller_count 2. Remove it after testing. Do not
run mutation/browser itinerary checks against personal records.

## Final verification

- 568 tests passed across Student 4, MCP and AI-Mode; one existing Pydantic-settings warning.
- Ruff lint/format passed; strict mypy passed for 76 files.
- Backend/database image builds and Compose configuration checks passed.
- Two independent review passes checked numeric parsing, tool validation, fresh
  final reads and schedule enforcement. Reproduced and fixed inclusive-minimum
  inversion, unsupported negated bounds, malformed raw arguments and context overflow.
- Full logs are in `verification.txt`; live results retain the initial failures.
