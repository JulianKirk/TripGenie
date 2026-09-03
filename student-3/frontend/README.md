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
| `STUDENT3_FRONTEND_AI_TIMEOUT_SECONDS` | `150` | Timeout for the AI suggestion route only. |
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
| `GET,POST /suggestions` | Ask for AI transport suggestions. Saves nothing |
| `GET /health` | Service status plus the backend dependency. Always `200`. |
| `GET /ready` | `200` when the backend is reachable, `503` otherwise. |

Filters cover type, provider, origin, destination, availability, price range,
and departure window. Blank fields are dropped rather than forwarded, because
the backend treats a blank query value as invalid rather than unset.

## Input controls

Free-text identifiers are unreliable and give no clue what to type, so the forms
use real controls wherever the value allows one:

| Field | Control |
| --- | --- |
| Trip | Picker of trip names read through from Student 1, falling back to text if that service is down |
| Transport option | Picker labelled by route, provider, type, departure and price |
| Dates | Native date picker. Its value format is already `YYYY-MM-DD` |
| Departure / arrival | Native date-and-time picker, value format already `YYYY-MM-DDTHH:MM` |
| Time zones | Picker of real UTC offsets, submitting the minutes the API expects |
| Price, capacity, travellers, cost | Number inputs with sensible min, max and step |
| Type, availability, plan state | Pickers |

The trip picker is the only one with an external dependency. If Student 1's
service is unreachable the field degrades to a text input with a note, so
transport planning still works during their outage.

## AI suggestions

`/suggestions` asks the backend for advisory guidance drafted by a local model
from options already in TripGenie. The screen is built so a traveller can never
mistake advice for stored data:

- The draft panel is tagged **advisory only** and states that nothing has been
  saved, naming the model, provider and run id that produced it.
- Each suggestion's action is **"Review and add to a trip"** — a link to the
  ordinary planning form with the option prefilled, never a save. Adding
  transport stays a deliberate human act.
- Suggestions render as the real option records, so every figure shown is the
  stored one rather than something the model wrote.
- When AI-Mode is unavailable the error renders in the panel with the form
  intact and the shell navigable; every other screen is unaffected.

Only this route gets the long timeout, because a local model answering a cold
prompt takes far longer than the few seconds that is generous elsewhere.

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

## Running it

```bash
docker compose up --build student-3      # frontend, backend and database
```

Then open the Transport Management link on the shared home page at
<http://localhost:8080>, or go straight to <http://localhost:8093>.

`student-3` is not a real service: it is a name for the group, and the container
exits as soon as the three services it depends on are healthy. Bring up a single
service by name if you prefer, for example `docker compose up student-3-backend`.

Only the frontend publishes a host port. The backend and database are reachable
only inside the Compose network, which is what keeps the boundary honest.

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
