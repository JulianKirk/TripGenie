# Student 3 backend service

This FastAPI service exposes the public TripGenie Student 3 `/api` transport surface. It
talks to the Student 3 database service over HTTP only and never opens the SQLite file.

## Scope: plan records, not reservations

TripGenie does not book transport. A `transport-bookings` record is a **saved plan entry** —
"this transport is part of my trip". No reservation is placed with a carrier and no payment
is taken. `estimated_cost` is a planning figure, which is what the Student 5 budget feature
consumes; it is never an amount charged.

`booking_status` is therefore a plan state, not a carrier state:

| Value | Meaning |
| --- | --- |
| `pending` | Shortlisted, still being considered |
| `confirmed` | Committed to the itinerary |
| `cancelled` | Removed from the plan |
| `completed` | Journey taken |

## Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `STUDENT3_BACKEND_API_PREFIX` | `/api` | Public API prefix. |
| `STUDENT3_BACKEND_DB_API_BASE_URL` | `http://student-3-database:8004` | Student 3 database service. |
| `STUDENT3_BACKEND_DB_API_PREFIX` | `/internal` | Database API prefix. |
| `STUDENT3_BACKEND_DB_API_TIMEOUT_SECONDS` | `5` | Timeout for backend-to-database calls. |
| `STUDENT3_BACKEND_SERVICE_NAME` | `student-3-backend` | Name reported by health endpoints. |
| `STUDENT3_BACKEND_TRIPS_API_BASE_URL` | `http://student-1-backend:8001` | Student 1 trips API, used only by the optional trip check. |
| `STUDENT3_BACKEND_TRIPS_API_PREFIX` | `/api` | Trips API prefix. |
| `STUDENT3_BACKEND_TRIPS_API_TIMEOUT_SECONDS` | `5` | Timeout for the trip lookup. |
| `STUDENT3_BACKEND_VERIFY_TRIP_EXISTS` | `false` | Opt in to checking trips against Student 1. |

## API surface

Responses wrap payloads in a `data` envelope; failures use the shared
`{"error": {"code", "message", "details"}}` shape.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Service status plus the database dependency. Always `200`. |
| `GET` | `/ready` | `200` when the database is reachable, `503` otherwise. |
| `GET` | `/api/transport-options` | List and filter options. |
| `GET` | `/api/transport-options/compare` | Side-by-side selection, `?ids=` up to 4. |
| `POST` | `/api/transport-options` | Create an option. |
| `GET` | `/api/transport-options/{transportId}` | Fetch one option. |
| `PATCH` | `/api/transport-options/{transportId}` | Partially update an option. |
| `DELETE` | `/api/transport-options/{transportId}` | Delete an option with no plan entries. |
| `GET` | `/api/transport-options/{transportId}/plan-entries` | Plan entries for one option. |
| `GET` | `/api/transport-bookings` | List and filter plan entries. |
| `POST` | `/api/transport-bookings` | Add transport to a trip. |
| `GET` | `/api/transport-bookings/{bookingId}` | Fetch one plan entry. |
| `PATCH` | `/api/transport-bookings/{bookingId}` | Partially update a plan entry. |
| `DELETE` | `/api/transport-bookings/{bookingId}` | Remove a plan entry. |
| `GET` | `/api/trip-directory` | Trips available for selection, read through from Student 1. |
| `GET` | `/api/trips/{tripId}/transport` | **Composed view** — everything planned for one trip. |

### Filters

`GET /api/transport-options` accepts `type`, `provider`, `origin`, `destination`,
`availability_status`, `min_price`, `max_price`, `departure_from`, `departure_to`.
`GET /api/transport-bookings` accepts `trip_id`, `transport_id`, `booking_status`.
Unsupported query parameters return `400` rather than being ignored, and reversed ranges
return `422`.

### `GET /api/trips/{tripId}/transport`

The database service has no equivalent route: it would have to join two tables on a
caller's behalf using a trip identifier it does not own. The backend composes it instead,
returning each plan entry joined to its option, ordered by departure, plus:

- `entry_count` — every entry for the trip
- `active_entry_count` — entries that still count (`pending`, `confirmed`, `completed`)
- `estimated_cost_total` — summed over active entries only, in whole cents

### `GET /api/transport-options/compare`

Accepts `?ids=a,b` or repeated `?ids=a&ids=b`, up to **4** options. Duplicates are rejected,
and an unknown identifier returns `404` rather than being silently dropped — a caller must
never be shown a shorter comparison than it asked for.

## Business rules owned here

- **Route sanity.** `origin` must differ from `destination`, checked case-insensitively.
  `car_rental` is exempt: collecting and returning a vehicle at one depot is normal. A
  `PATCH` is validated against the merged record, so it cannot collapse a route.
- **Ordered ranges.** `min_price` above `max_price`, or `departure_from` after
  `departure_to`, returns `422` before the database is called.
- **Comparison limits.** At most 4 distinct options per request.
### `GET /api/trip-directory`

A read-only convenience lookup so the UI can offer trip names instead of asking
for a typed identifier. Student 3 does not own trips, which is why this is a
directory rather than `/api/trips`.

Always returns `200`. When Student 1 cannot be reached it reports
`{"available": false, "trips": []}` — distinguishable from a genuine empty list,
so a caller can fall back to free text rather than claiming there are no trips.

- **Optional trip check.** With `STUDENT3_BACKEND_VERIFY_TRIP_EXISTS=true`, plan entries are
  checked against Student 1's trips API. Only a definitive `404` blocks the write; a timeout
  or an unreachable service does not, so transport planning survives that outage. Off by
  default.

Everything else — derived `duration_minutes` and `seats_remaining`, capacity limits, the
`estimated_cost` default, delete-restrict — stays in the database service, which remains the
final validation guard.

## Status codes

| Code | Meaning |
| --- | --- |
| `400 BAD_REQUEST` | Unsupported query parameter. |
| `404 NOT_FOUND` | Unknown option or plan entry. |
| `409 CONFLICT` | Duplicate id, capacity exceeded, or option still referenced. |
| `422 VALIDATION_ERROR` | Field or business-rule validation failure. |
| `502 BAD_GATEWAY` | Database service returned something unusable. |
| `503 DEPENDENCY_UNAVAILABLE` | Database service unreachable. |
| `504 DEPENDENCY_TIMEOUT` | Database service too slow. |

## Local checks

```bash
cd student-3
python -m pip install -e .[dev]
python -m ruff check backend/student3_backend_service tests/backend
python -m pytest tests/backend
```

The backend suite runs the **real** database service in-process rather than a stub, so every
test exercises the true contract, including its validation and error envelopes.
