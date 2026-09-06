# Student 4: Activities and Attractions

This file supplements the repository-level `AGENTS.md` for `student-4/`.

## Ownership and source of truth

- Student 4 owns activities and attractions, represented by the single
  `Activity` aggregate. Read `docs/object-model.md` before changing entities,
  validation, availability, accessibility, category, or pricing semantics.
- `frontend/` serves port 8084, `backend/` exposes the public activity contract
  on port 8008, and `database/` exposes its private contract on port 8009.
- Keep `docs/backend-service-api.md`, `docs/database-service-api.md`, and
  `docs/frontend-service.md` synchronized with route, schema, or UI behavior.
- Release architecture and data-design evidence is under
  `../docs/reports/release-0/Student4/`; update source Markdown before
  regenerating or replacing rendered diagrams.

## Domain and integration rules

- Store shared country and city UUIDs locally, but resolve and validate names
  through the shared backend. The database service does not make outbound calls.
- Add activities to trips through Student 1. Never write itinerary associations
  into the activity database.
- Serialize AUD prices as exact two-decimal strings and calculate with
  `Decimal`. Respect `PER_PERSON` versus `FLAT_ADMISSION` semantics.
- Preserve nullable accessibility values: `null` means unknown, not false.
- Availability is local time and distinguishes weekly schedules from one-off
  dates. Enforce the aggregate invariants documented in the object model.
- AI search and recommendations go through AI-Mode, operate on authoritative
  catalogue results, expose chosen filters to the user, and never save without
  an explicit user action.
- Keep frontend query parsing and presentation in `query.py`, `forms.py`, and
  `presenters.py` rather than growing route handlers with duplicate logic.

## Development and verification

From the repository root:

```bash
python -m pip install -e "./student-4[dev]"
ruff check student-4
ruff format --check student-4
mypy --config-file student-4/pyproject.toml \
  student-4/backend/student4_backend_service \
  student-4/database/student4_database_service \
  student-4/frontend/student4_frontend_service \
  student-4/tests/backend student-4/tests/database \
  student-4/tests/e2e student-4/tests/frontend
pytest student-4/tests -q
docker compose config --quiet
```

For an isolated integrated smoke test:

```bash
docker compose up -d --build --wait --no-deps student-4-database student-4-backend student-4-frontend
curl --fail http://127.0.0.1:8084/ready
```

- Add regression tests at the narrowest layer and an end-to-end test when a
  public-to-database contract changes.
- Strict mypy applies to source and tests. Do not hide contract problems with
  broad ignores or `Any`; use a narrowly justified override only when a library
  boundary requires it.
- The checked-in `database/activities.db` is data, not a migration mechanism.
  Prefer deterministic seed and repository changes, and do not overwrite it as
  a side effect of tests.
