# Student 3: Transport Management

This file supplements the repository-level `AGENTS.md` for `student-3/`.

## Ownership and integration

- Student 3 owns transport options, comparison, and transport recommendations.
- `frontend/` serves port 8093, `backend/` exposes public `/api` routes on port
  8003, and `database/` exposes private `/internal` routes on port 8004.
- Port 8093 is intentional. Keep `docker-compose.yml`, the shared landing-page
  link, configuration examples, and smoke tests aligned if it changes.
- The backend uses Student 1 for trip selection and itinerary association.
  Transport browsing and comparison must continue when Student 1 or AI-Mode is
  unavailable unless the requested operation intrinsically needs that service.
- AI recommendations are advisory, use the packaged prompt asset, and may only
  recommend authoritative transport records.
- Read the README in each layer before changing its behavior or contract.

## Development and verification

Run from `student-3/` after `python -m pip install -e ".[dev]"`:

```bash
python -m compileall database/student3_database_service tests/database
python -m pytest tests/database
python -m compileall backend/student3_backend_service tests/backend
python -m pytest tests/backend
python -m compileall frontend/student3_frontend_service tests/frontend
python -m pytest tests/frontend
```

Run Ruff from the repository root for the affected package and tests. Validate
images and the isolated Compose slice when integration settings change:

```bash
docker compose config --quiet
docker compose up -d --build --wait --no-deps student-3-database student-3-backend student-3-frontend
```

Clean up with `docker compose down -v` only when all local TripGenie Compose
volume data may be removed. Test money and capacity rules without floats,
downstream clients with injected transports, and full-page plus HTMX flows in
frontend tests.
