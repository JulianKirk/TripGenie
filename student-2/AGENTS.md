# Student 2: Accommodation Management

This file supplements the repository-level `AGENTS.md` for `student-2/`.

## Ownership and integration

- Student 2 owns accommodation catalogue data and search. Read
  `accommodation-service.md` plus `docs/object-model.md` before changing domain
  semantics.
- `frontend/` serves port 9003, `backend/` exposes the public service on port
  9000, and `database/` is private on port 9001.
- The backend resolves locations through the shared reference backend and adds
  stays to itineraries through Student 1. The frontend calls only Student 2's
  backend.
- AI search goes through AI-Mode and must resolve generated filters against the
  real accommodation catalogue. It must not invent records or save a stay
  without an explicit user action.
- Keep `docs/backend-service-api.md`, `docs/database-service-api.md`, and
  `docs/frontend-service.md` synchronized with implementation changes.

## Development and verification

Student 2 end-to-end tests use the real shared packages. From the repository
root:

```bash
python -m pip install -e "./shared[dev]" -e "./student-2[dev]"
ruff check student-2
ruff format --check student-2
pytest student-2/tests -q
docker build -f student-2/database/Dockerfile -t student-2-database student-2
docker build -f student-2/backend/Dockerfile -t student-2-backend student-2
docker build -f student-2/frontend/Dockerfile -t student-2-frontend student-2
docker compose config --quiet
```

- Preserve the distinction between shared location IDs and public names.
- Test repository filters and invariants in `tests/database`, downstream and
  public contracts in `tests/backend`, rendered/HTMX behavior in
  `tests/frontend`, and real backend/database/shared wiring in `tests/e2e`.
- The backend and frontend may return a successful `/health` response whose
  payload says `degraded` when a downstream service is absent. Preserve that
  distinction between a serving process and a healthy dependency chain.
