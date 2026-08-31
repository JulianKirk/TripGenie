# Student 3 frontend service

The browser UI for Transport Management. A FastAPI service that renders Jinja2
templates and uses HTMX to swap the app shell, so every screen works as a plain
server-rendered page and gets progressive enhancement on top.

It calls the Student 3 backend `/api` surface only. It never reaches the
database service or the SQLite file.

## Scope: plan transport, do not book it

TripGenie does not book transport. Adding an option to a trip saves a **plan
entry** — no reservation is placed with a carrier and no payment is taken. The
UI wording reflects this ("Add to trip", "Planned transport", "Remove from
trip"), and a test asserts no screen promises a transaction.

Plan states are shown in the traveller's language rather than raw enum values:

| Stored value | Shown as |
| --- | --- |
| `pending` | Shortlisted |
| `confirmed` | In the itinerary |
| `cancelled` | Removed |
| `completed` | Journey taken |

## Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `STUDENT3_FRONTEND_BACKEND_BASE_URL` | `http://student-3-backend:8003` | Student 3 backend API. |
| `STUDENT3_FRONTEND_BACKEND_API_PREFIX` | `/api` | Backend API prefix. |
| `STUDENT3_FRONTEND_BACKEND_TIMEOUT_SECONDS` | `5` | Timeout for frontend-to-backend calls. |
| `STUDENT3_FRONTEND_SERVICE_NAME` | `student-3-frontend` | Name reported by health endpoints. |

## Ports

Serves on **8093**, which is the port `shared/frontend/index.html` links for
Student 3.

## Screens

| Route | Purpose |
| --- | --- |
| `GET /` | Browse and filter transport options |
| `GET /compare` | Side-by-side comparison, up to 4 options |
| `GET /options/new`, `POST /options` | Add an option |
| `GET /options/{id}` | Option detail, plus the trips planning it |
| `GET,POST /options/{id}/edit` | Edit an option |
| `GET,POST /options/{id}/delete` | Remove an option, with a confirmation step |
| `GET /trips/{tripId}/transport` | Everything planned for one trip, with a running estimate |
| `GET /plan/new`, `POST /plan` | Add transport to a trip |
| `GET,POST /plan/{id}/edit` | Edit a plan entry |
| `GET,POST /plan/{id}/delete` | Remove a plan entry, with a confirmation step |
| `GET /health` | Service status plus the backend dependency. Always `200`. |
| `GET /ready` | `200` when the backend is reachable, `503` otherwise. |

Filters cover type, provider, origin, destination, availability, price range,
and departure window. Blank fields are dropped rather than forwarded, because
the backend treats a blank query value as invalid rather than unset.

## Design notes

- **The backend owns validation.** Forms post whatever was typed; when the
  backend rejects it, the field-level messages are rendered next to the inputs
  and the submitted values are preserved so nothing is retyped.
- **`duration_minutes` and `seats_remaining` are never form fields** — they are
  derived server-side, so the forms would be lying if they offered them.
- **Cross-timezone legs are flagged.** Where an option carries UTC offsets, the
  duration is marked as measured in UTC, because the wall-clock times alone
  would suggest a different journey length.
- **Availability and seats are shown together.** `availability_status` is
  operator-declared and is not derived from the seat count, so presenting either
  one alone would mislead.
- **Errors render as panels, not stack traces.** A dependency failure shows the
  error code, message, and a retry link while keeping the shell navigable.

## Styling

`static/css/styles.css` deliberately mirrors the Student 1 frontend's visual
language so the integrated application reads as one product. The specification
requires a shared team theme, and `shared/frontend/css/` is still empty — when
the team lands one, this file should shrink to Student 3 specifics.

## Local checks

```bash
cd student-3
python -m pip install -e .[dev]
python -m ruff check frontend/student3_frontend_service tests/frontend
python -m pytest tests/frontend
```

The frontend suite runs the **real** backend and the **real** database
in-process rather than stubbing them, so the templates are asserted against the
contracts the services genuinely produce.
