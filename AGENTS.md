# TripGenie Agent Instructions

This is an intentionally small initial instruction file. The team expects to
expand it with repository architecture, development, testing, and contribution
guidance later. Extend this file as those conventions are agreed; do not treat
the current Graphify guidance as the complete project instructions.

## Graphify

- For questions about repository architecture, service relationships, or file
  dependencies, consult `graphify-out/GRAPH_REPORT.md` and
  `graphify-out/graph.json` before performing a broad source scan.
- When the Graphify CLI is available, prefer `graphify query`, `graphify path`,
  or `graphify explain` to retrieve a focused subgraph.
- Treat the repository source and service documentation as authoritative. The
  graph is a navigation aid and may lag changes on an unmerged branch.
- The `Graphify Update` GitHub Actions workflow refreshes the shared code graph
  after changes reach `main`; contributors do not need local Git hooks.
- `graphify update .` refreshes code relationships only. Documentation, paper,
  and image changes require semantic extraction with a supported LLM backend.
  Never imply that those relationships were refreshed by the code-only job.

## Version control

- Do not create, amend, or push a commit unless the user explicitly approves it
  after having the opportunity to review the changes locally.

## Linting

- Run service linting and formatting from the repository root with the shared
  `ruff.toml` configuration: `ruff check <service-path>` and
  `ruff format --check <service-path>`.
- A service-specific `pyproject.toml` may add narrowly scoped overrides, but it
  must extend the root configuration rather than replace the shared rule set.
- Apply the shared rules to new and modified service code. Existing violations
  elsewhere in the repository can be handled in a separate cleanup change.
