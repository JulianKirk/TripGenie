# TripGenie Agent Instructions

These instructions apply to the entire repository. A nearer `AGENTS.md` adds
rules and context for its subtree; follow both, with the nearer file taking
precedence when guidance differs.

## Product and ownership map

TripGenie is a Python 3.11 microservice application built with FastAPI,
server-rendered Jinja templates and HTMX, SQLite, Docker Compose, and a shared
AI gateway backed by a host-managed Ollama runtime.

| Path | Responsibility |
| --- | --- |
| `student-1/` | Trips and itinerary management |
| `student-2/` | Accommodation catalogue and itinerary integration |
| `student-3/` | Transport catalogue and trip integration |
| `student-4/` | Activities and attractions catalogue and itinerary integration |
| `student-5/` | Budgets, expenses, and cross-service cost summaries |
| `shared/` | Country, city, and currency reference data plus the landing page |
| `ai-services/ai-mode/` | The only application service that communicates with Ollama |
| `ai-services/agentic-loop/` | CI-oriented service smoke and review harness |
| `docs/` | Architecture decisions and release evidence |

Read the nearest service documentation before changing a contract. In
particular, use `*/docs/*-service-api.md` and `*/docs/object-model.md` where
they exist; use `docs/architecture/` for cross-service decisions.

## Architecture rules

- Each student slice has a frontend, public backend, private database service,
  and tests. Keep browser-facing concerns in the frontend, orchestration and
  public contracts in the backend, and persistence in the database service.
- A frontend calls its own backend. It must not call a database service or
  another student's service directly.
- A backend is the sole caller of its database service. Database endpoints are
  internal implementation details and are not published to the host by
  Compose.
- Services own their data. Do not read another service's SQLite file or import
  another service's persistence models. Integrate over the documented HTTP API.
- Student 1 owns trips and itinerary associations. Student services add or
  resolve itinerary items through Student 1's public API.
- The shared reference service owns country, city, currency, and conversion
  reference data. Feature databases may store its stable identifiers, but
  location names and currency data are resolved through the shared backend.
- `ai-mode` is the sole Ollama adapter. Feature backends call it over HTTP and
  must keep their non-AI workflows usable when AI is unavailable.
- Preserve `/health` versus `/ready` semantics. Health reports whether the
  process serves; readiness may depend on required downstream services.
- Treat API schemas, money representation, enum values, route prefixes, and
  environment-variable names as contracts. Update producers, consumers,
  contract tests, documentation, and Compose together when they change.

## Repository navigation

- Start with the scoped `AGENTS.md`, service README, API documentation, and
  tests for the code being changed.
- Use `docker-compose.yml` as the source of truth for integrated service names,
  ports, dependencies, volumes, and Compose-only URLs.
- Use the corresponding `.github/workflows/*-ci.yml` as the source of truth for
  the checks a pull request must pass.
- Prefer focused searches with `rg` or `rg --files`; do not scan generated
  Graphify output, SQLite files, vendored JavaScript, or virtual environments.
- Make the smallest coherent cross-service change. Avoid opportunistic
  refactors in student-owned slices that are unrelated to the requested work.

## Local development

Create a virtual environment with Python 3.11, then install only the slice you
are changing. Examples, run from the repository root:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e "./student-4[dev]"
```

Other editable installs follow the same pattern (`./shared[dev]`,
`./student-1[dev]`, and so on). Student 2 end-to-end tests also require
`./shared[dev]`. The AI-Mode and agentic-loop subtrees have their own setup
commands in `ai-services/AGENTS.md`.

For an integrated run, Ollama is managed on the host, not by Compose. Follow
`README.md` and `shared/configuration/.env.example`, then run:

```bash
docker compose --env-file shared/configuration/.env.example config --quiet
docker compose --env-file shared/configuration/.env.example up --build -d
docker compose --env-file shared/configuration/.env.example ps
```

The example environment file is documentation; application processes do not
load it automatically. Never commit real credentials or local secrets.

To exercise one owned slice without optional cross-service dependencies, copy
the exact `docker compose up --no-deps ...` form from that slice's CI workflow.
Use `docker compose down -v` only when deleting local persisted test data is
intended.

## Testing and quality checks

Run checks from the repository root unless a scoped file says otherwise.

```bash
ruff check <service-path>
ruff format --check <service-path>
pytest <test-path> -q
docker compose config --quiet
```

- The root `ruff.toml` is the shared lint and formatting policy. A service
  `pyproject.toml` may extend it with narrow overrides but must not replace it.
- Add or update tests in the matching `tests/backend`, `tests/database`,
  `tests/frontend`, or `tests/e2e` directory. Prefer app factories and injected
  HTTP transports over live network calls in unit tests.
- Run the narrowest relevant test first, then the complete affected slice.
- Run formatting checks as well as linting when the slice's CI does so.
- Student 4 additionally requires strict mypy checks; see its scoped guidance.
- Build affected images and validate Compose after Dockerfiles, package data,
  environment variables, ports, health checks, or service dependencies change.
- Do not weaken an assertion, lint rule, type rule, health check, or CI gate just
  to make a change pass. Fix the behavior or document a justified narrow
  exception.

## Implementation conventions

- Preserve the existing `create_app(...)` factory pattern and dependency
  injection hooks so tests can replace downstream HTTP transports.
- Keep settings parsing in each package's `config.py`; do not scatter direct
  environment reads through route handlers or business logic.
- Keep transport failures at service boundaries and translate them through the
  slice's existing error types. Do not expose raw dependency exceptions to UI
  callers.
- Use Pydantic models for wire contracts and SQLAlchemy models only inside the
  owning database service. Do not return ORM instances across service layers.
- Use `Decimal` and the established JSON string representation for money. Never
  introduce binary floating-point arithmetic for persisted or exchanged costs.
- Keep HTMX responses as focused partial templates and ordinary navigation as
  full-page templates. Preserve accessible labels, focus behavior, live-region
  announcements, and non-JavaScript form behavior.
- Prompt assets are package data. If a prompt is added or renamed, update the
  relevant `pyproject.toml`, configuration/defaults, and tests.

## Documentation and generated artifacts

- Update API and object-model documentation in the same change as a contract or
  persistence-model change. Record cross-service architectural decisions under
  `docs/architecture/decisions/` when the rationale will matter later.
- Keep release evidence under the existing `docs/reports/release-*` structure.
  Do not claim a check or runtime result without capturing reproducible evidence.
- Do not hand-edit generated Graphify outputs. The `Graphify Update` workflow
  refreshes code relationships after changes reach `main` and opens a follow-up
  pull request containing the portable graph artifacts.

## Graphify

- For repository architecture, service relationships, or file dependencies,
  consult `graphify-out/GRAPH_REPORT.md` and `graphify-out/graph.json` before a
  broad source scan.
- When available, prefer `graphify query`, `graphify path`, or
  `graphify explain` for a focused subgraph.
- Treat source code, service documentation, Compose, and CI workflows as
  authoritative. The graph is a navigation aid and may lag an unmerged branch.
- `graphify update .` refreshes code relationships only. Documentation, paper,
  and image changes require semantic extraction with a supported LLM backend;
  never imply that the code-only workflow refreshed those relationships.

## Version control

- Inspect `git status` before editing and preserve unrelated user changes.
- Keep commits focused, but do not create, amend, or push a commit unless the
  user explicitly approves it after reviewing the local changes.
- Do not rewrite shared history or use destructive cleanup commands to resolve
  unrelated worktree state.
