# ADR-0002: Treat internal API and observability details as TripGenie proposals

## Status
Proposed

## Context

Visible Labs 01-04 require evidence-backed browser checks, `curl` checks, database evidence, prompt assets, implementation/review outputs, human decisions, and reruns. Lab 04 also shows stage banners such as `[START]`, `[OBSERVE]`, `[PROMPTS]`, `[LLM]`, and `[DONE]`. The visible labs do not, however, clearly mandate `/internal/*`, `/health`, `/ready`, exact JSON envelopes, run IDs, correlation IDs, or fixed retry counts.

Earlier Student 1 PR documentation described several of those details as though they were part of the assessed course loop. That wording risked overstating project conventions as subject requirements.

## Decision

- Keep public CRUD and AI suggestion routes documented as Release 0 **project proposals** until implementation evidence exists.
- If Student 1 adopts `/internal/*` backend-to-database routes, `/health` or `/ready` endpoints, structured run/correlation IDs, retry caps, or an exact log schema, label each item explicitly as a TripGenie design choice.
- Use manual Expected/Actual/Pass-Fail evidence, browser checks, `curl` checks, database checks, prompt outputs, review outputs, and human decisions as the primary assessed proof set.
- Do not claim any project-specific observability or runtime behaviour as implemented until it has been run and evidenced.

## Consequences

- Course-aligned documentation stays evidence-backed and avoids inventing requirements.
- Project-specific operational detail can still guide implementation when it is clearly labelled.
- Future implementation can promote any adopted convention from proposed to implemented once validation evidence is available.
