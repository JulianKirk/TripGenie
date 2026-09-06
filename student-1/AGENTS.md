# Student 1: Trips and Itineraries

This file supplements the repository-level `AGENTS.md` for `student-1/`.

## Ownership and integration

- Student 1 owns trips, itinerary items, and the associations that attach
  accommodation, transport, and activities to a trip.
- `frontend/` serves the trip UI on port 8081, `backend/` exposes the public
  `/api` contract on port 8001, and `database/` exposes the private `/internal`
  contract on port 8002.
- The backend may read public details from Students 2, 3, and 4 to enrich an
  itinerary. Keep those calls in the existing typed client modules and preserve
  useful degraded behavior when an optional feature service is unavailable.
- AI suggestions go through the shared AI-Mode service. Prompt assembly and
  deterministic trip rules remain local; model output must not silently mutate
  itinerary state.
- Consult `backend/README.md`, `frontend/README.md`, and the Student 1 documents
  under `../docs/architecture/` before changing service boundaries.

## Development and verification

Run from `student-1/` after `python -m pip install -e ".[dev]"`:

```bash
python -m compileall database/database_service tests/database
python -m pytest tests/database
python -m compileall backend/backend_service tests/backend
python -m pytest tests/backend
python -m compileall frontend/frontend_service tests/frontend
python -m pytest tests/frontend
```

Run Ruff from the repository root with the affected source and test paths, then
build affected images using `student-1/{database,backend,frontend}/Dockerfile`.
Backend development that imports the AI-Mode contract may also require, from
the repository root:

```bash
python -m pip install -e ./ai-services/ai-mode
```

- Keep itinerary referential and uniqueness rules covered in database tests.
- Keep downstream client failures and public response contracts covered in
  backend tests; use injected transports rather than live services.
- Keep HTMX partial behavior, full-page fallbacks, and trip-detail integration
  covered in frontend tests.
