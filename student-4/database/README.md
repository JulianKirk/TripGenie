# Student 4 database service

Internal FastAPI and SQLite service for Student 4 activities and attractions.
The implemented contract is documented in
[`../docs/database-service-api.md`](../docs/database-service-api.md).

## Local development

From the repository root:

```bash
uv venv .venv --python 3.11
uv pip install --python .venv/bin/python -e './student-4[dev]'
.venv/bin/pytest student-4/tests/database
.venv/bin/ruff check student-4
.venv/bin/ruff format --check student-4
.venv/bin/mypy --config-file student-4/pyproject.toml \
  student-4/database/student4_database_service student-4/tests/database
```

Run the service directly:

```bash
DATABASE_URL=sqlite:///student-4/database/activities.db \
  .venv/bin/uvicorn student4_database_service.app:app \
  --app-dir student-4/database --port 8009
```

`SEED_DATA=0` disables seeding. By default, an empty database receives ten
fixed categories and ten sample activities. Seed operations are idempotent and
do not overwrite an existing activity catalogue. A populated development
database is included at `student-4/database/activities.db` for assignment
inspection.

## Container

```bash
docker build -f student-4/database/Dockerfile -t student-4-database student-4
docker run --rm -p 8009:8009 student-4-database
curl http://localhost:8009/internal/health
```
