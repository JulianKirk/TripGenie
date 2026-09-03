# Student 4 Activities Frontend

This HTMX microservice renders the activities and attractions catalogue. It
speaks only to the Student 4 backend API: the browser and this package never
call the database, shared location service, or itinerary service directly.

## Features

- Live text, location, category, price, duration, party, age, accessibility,
  booking, date, time, sorting, and paging filters.
- Server-rendered activity cards and full detail dialogs.
- One catalogue view with create and edit controls, activation state, and
  explicit permanent-delete confirmation in the edit flow.
- Add activities to a trip, reschedule them, and remove selections through
  Student 4's itinerary proxy.
- Ask for trip-aware AI suggestions, see the advanced filters it runs and any
  one-time revision, and review a grounded shortlist of real activities.
- Progressive enhancement: the initial page and explicit search submission
  work without JavaScript; HTMX adds live fragment updates.
- Degraded health and safe HTML error states when the backend is unavailable.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `BACKEND_URL` | `http://student-4-backend:8008` | Student 4 backend base URL. |
| `BACKEND_TIMEOUT` | `5` | Positive request timeout in seconds. |
| `AI_TIMEOUT` | `210` | Positive timeout for AI planning and evaluation calls only. |

## Run locally

From the repository root:

```bash
python -m venv .venv
.venv/bin/pip install -e './student-4[dev]'
BACKEND_URL=http://127.0.0.1:8008 \
  .venv/bin/uvicorn student4_frontend_service.app:app \
  --host 127.0.0.1 --port 8084
```

Browse and manage entries at `http://127.0.0.1:8084/`.

The temporary Compose service is published on `http://localhost:8094` while
the legacy `student-4-service` placeholder continues to own port 8084.

## HTML routes

| Route | Purpose |
|---|---|
| `GET /` | Unified catalogue and management page, including inactive entries. |
| `GET /activity` | Search results and pagination fragment. |
| `GET /activity/{id}` | Full activity detail dialog. |
| `GET /activity/{id}/itineraries/dialog` | Direct trip-picker dialog. |
| `GET /manage` | Legacy catalogue management page. |
| `GET /manage/activity/new` | Create form fragment. |
| `POST /manage/activity` | Create an aggregate through Student 4. |
| `GET /manage/activity/{id}/edit` | Prefilled edit form. |
| `PUT` or `POST /manage/activity/{id}` | Replace the complete aggregate. |
| `GET /manage/activity/{id}/delete` | Delete confirmation. |
| `DELETE /manage/activity/{id}` | Delete through Student 4. |
| `GET /activity/{id}/itineraries` | Itinerary picker. |
| `PUT /activity/{id}/itineraries/{trip_id}` | Add or reschedule. |
| `DELETE /activity/{id}/itineraries/{trip_id}` | Remove selection. |
| `GET /health` | Frontend and backend status. |
| `POST /suggestions/plan` | Plan an advanced search from a prompt and optional trip. |
| `POST /suggestions/evaluate` | Evaluate real matches and render a shortlist or one retry. |

Backend validation remains authoritative. Browser forms are translated into
allow-listed structured payloads; no arbitrary browser JSON is forwarded.

## Quality checks

```bash
.venv/bin/pytest student-4/tests/frontend -q
.venv/bin/ruff check student-4/frontend student-4/tests/frontend
.venv/bin/ruff format --check student-4/frontend student-4/tests/frontend
.venv/bin/mypy --config-file student-4/pyproject.toml \
  student-4/frontend/student4_frontend_service student-4/tests/frontend
docker build -f student-4/frontend/Dockerfile \
  -t student-4-frontend student-4/frontend
```
