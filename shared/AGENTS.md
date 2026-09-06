# Shared Reference Service Guidance

This file supplements the repository-level `AGENTS.md` for `shared/`.

## Scope and boundaries

- The shared service owns countries, cities, currencies, and currency conversion
  reference data. Read `shared-service.md` and `docs/object-model.md` before
  changing that model.
- `backend/` exposes the public API on port 9100. It is the only caller of the
  private `database/` service on port 9101.
- Other slices may store shared UUIDs but must resolve and validate shared data
  through the backend API. Avoid adding feature-specific business rules here.
- `frontend/index.html` is the shared landing page. Keep its links aligned with
  the frontend ports published by `docker-compose.yml`.
- Maintain public and internal contracts in `docs/backend-service-api.md` and
  `docs/database-service-api.md` alongside schema or route changes.

## Development and verification

From the repository root:

```bash
python -m pip install -e "./shared[dev]"
ruff check shared
ruff format --check shared
pytest shared/tests -q
docker build -f shared/database/Dockerfile -t shared-database shared
docker build -f shared/backend/Dockerfile -t shared-backend shared
docker compose config --quiet
```

- Database and repository behavior belongs in `tests/database`; public API and
  backend-to-database behavior belongs in `tests/backend` and `tests/e2e`.
- Keep IDs stable and validate city/country relationships at the owning service.
- Preserve the documented degraded-but-serving `/health` response when the
  backend cannot reach its database; do not turn that state into a process-level
  failure without changing its consumers and tests.
- Update `configuration/.env.example` when adding integrated configuration,
  with safe example values and comments distinguishing host from Compose URLs.
