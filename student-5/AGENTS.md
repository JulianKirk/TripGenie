# Student 5: Budget and Expense Management

This file supplements the repository-level `AGENTS.md` for `student-5/`.

## Ownership and integration

- Student 5 owns budgets, expenses, summaries, and cost analysis. It consumes
  trip, transport, accommodation, and activity APIs; it does not own or mutate
  those providers' catalogue records.
- `frontend/` serves port 8085, `backend/` exposes public `/api` routes on port
  8005, and `database/` exposes private `/internal` routes on port 8007.
- Keep all persisted and exchanged money exact. Use `Decimal` and canonical
  two-decimal strings; never introduce floats for totals, limits, or expenses.
- A summary must distinguish unavailable provider data from a genuine zero
  cost. Keep ordinary budget and expense CRUD usable when optional provider or
  AI services are unavailable.
- AI budget analysis goes through AI-Mode and is advisory; deterministic totals
  and validation remain authoritative.

## Development and verification

Run from `student-5/`:

```bash
python -m pip install -e ".[dev]"
python -m compileall backend database frontend tests
python -m ruff check backend database frontend tests
python -m pytest
```

From the repository root, validate images and integration when needed:

```bash
docker build -f student-5/database/Dockerfile -t student-5-database student-5
docker build -f student-5/backend/Dockerfile -t student-5-backend student-5
docker build -f student-5/frontend/Dockerfile -t student-5-frontend student-5
docker compose config --quiet
docker compose up -d --build --wait --no-deps student-5-database student-5-backend student-5-frontend
```

- Put persistence and arithmetic invariants in database/repository tests,
  provider translation and degradation in backend tests, and form plus summary
  rendering in frontend tests.
- Use the existing typed provider clients and injected transports. Do not make
  route handlers perform ad hoc cross-service requests.
- Update `database/README.md` when internal storage behavior or its API changes.
