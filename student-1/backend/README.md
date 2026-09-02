# Student 1 backend service

This FastAPI service exposes the public TripGenie Student 1 `/api` CRUD surface and talks to the Student 1 database service over HTTP only.

## Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `STUDENT1_BACKEND_API_PREFIX` | `/api` | Public API prefix. |
| `STUDENT1_BACKEND_DB_API_BASE_URL` | `http://student-1-database:8002` | Base URL for the internal Student 1 database API. |
| `STUDENT1_BACKEND_DB_API_PREFIX` | `/internal` | Internal Student 1 database API prefix. |
| `STUDENT1_BACKEND_DB_API_TIMEOUT_SECONDS` | `5` | Timeout for backend-to-database HTTP calls. |
| `STUDENT1_BACKEND_OLLAMA_BASE_URL` | _unset_ | Optional Ollama URL reported by health status only in issue #10. |
| `STUDENT1_BACKEND_SERVICE_NAME` | `student-1-backend` | Service name reported by health endpoints. |

## Accommodations on a trip

A trip holds many accommodations and an accommodation sits on many trips, so the
link is its own table (`trip_accommodations`) rather than a column on either
side. This service owns it; the accommodation service (student 2) reads and
writes it over these four endpoints, and nothing else reaches the table.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/trips/{tripId}/accommodations` | The accommodations pinned to one trip. |
| `PUT` | `/api/trips/{tripId}/accommodations/{accommodationId}` | Pin one, for a stay window. Replaces an existing pin. |
| `DELETE` | `/api/trips/{tripId}/accommodations/{accommodationId}` | Unpin one. `404` if it was never pinned. |
| `GET` | `/api/accommodations/{accommodationId}/trips` | The reverse lookup: every trip holding one accommodation. |

`PUT` rather than `POST` because pinning the same accommodation twice must not be
a conflict. It *replaces* the pin rather than creating a second one, so
re-sending the same body changes nothing and sending different dates moves the
stay — a user correcting the dates they just entered has to see the correction
stick.

The pin records the stay window:

| Field | Required | Meaning |
| --- | --- | --- |
| `date` | No | Check-in date. Defaults to the trip's `start_date`. |
| `check_in_time` | No | Arrival time, `HH:MM`. |
| `check_out` | No | Check-out date. `null` means no departure recorded. |
| `check_out_time` | No | Departure time, `HH:MM`. |

```bash
curl -X PUT localhost:8001/api/trips/trip_2027_sydney_getaway/accommodations/acc_1 \
  -H 'Content-Type: application/json' \
  -d '{"date": "2027-04-02", "check_in_time": "15:00",
       "check_out": "2027-04-03", "check_out_time": "10:00"}'
```

The body is optional in full: without one the pin lands on the trip's first day
with no departure, which is all this endpoint could record before stay dates
existed. Both dates must fall inside the trip's own window and `check_out` may
not precede `date`; either mistake is the normal `422` validation envelope with
the offending field named. `GET /api/trips/{tripId}` returns the pins on the trip
detail as `accommodations`.

`date` is the check-in and kept its name from when it was the only date there
was; renaming it is a SQLite table rebuild for no user-visible gain.

The reverse lookup exists so a caller asking "which trips already hold this
accommodation?" makes one request rather than one per trip.

An `accommodationId` is minted by the accommodation service, so this service
validates it as a bounded `[A-Za-z0-9_-]` string rather than as a UUID — it
should not need changing when another service changes how it mints identifiers.

## Accommodation names and prices

A trip stores an accommodation's id and the stay; the name and the nightly rate
belong to **student 2**. `GET /api/trips/{tripId}` fetches them so the trip page
can show a name rather than a UUID, adding three read-only fields to each entry
in `accommodations`:

| Field | Meaning |
| --- | --- |
| `name` | Student 2's name for the accommodation |
| `price_per_night` | Its nightly rate |
| `total_price` | `price_per_night x nights`, where nights is the gap between `date` and `check_out` |

All three are `null` when student 2 cannot be reached, when it does not know the
id, or when there is nothing to multiply (no rate, or no `check_out` yet). The
trip still returns `200` — losing a name is not a reason to lose the trip. The
write endpoints are unchanged and still answer with exactly what they stored.

Configured by `STUDENT1_BACKEND_ACCOMMODATION_API_BASE_URL` (default
`http://student-2-backend:9000`) and `..._TIMEOUT_SECONDS`.

Note the two services now reference each other: student 2 calls this one to pin
accommodations to trips, and this one calls student 2 for the labels. That is a
runtime lookup in both directions, not a boot order, so `docker-compose.yml`
deliberately declares no `depends_on` from here to student 2 — it would be a
cycle compose refuses to start.

## Error responses

Every error, whatever the status, is the same envelope:

```json
{"error": {"code": "...", "message": "...", "details": [{"field": "...", "issue": "..."}]}}
```

The status distinguishes *what kind* of thing went wrong, and the two 4xx
validation codes are deliberately different conditions rather than two spellings
of one:

| Status | `code` | Raised when |
| --- | --- | --- |
| 400 | `BAD_REQUEST` | The request carries something this endpoint does not accept **at all** — an unknown query parameter. Each offending name is listed in `details`. |
| 422 | `VALIDATION_ERROR` | A value the endpoint *does* accept failed its constraints — a path id that does not match its pattern, or a body field out of range. |
| 404 | `NOT_FOUND` | The id was well-formed but nothing has it. |
| 502 | `BAD_GATEWAY` | A service behind this one answered with something unusable. |
| 503 | `DEPENDENCY_UNAVAILABLE` / `DEPENDENCY_TIMEOUT` | A service behind this one could not be reached in time. |

So `GET /api/trips/bad!id` is a `422` (the id is a value that failed a pattern)
while `GET /api/trips?bogus=1` is a `400` (there is no `bogus` parameter to
validate). Endpoints declare their own allowed parameters; anything else is
rejected rather than ignored, so a typo in a filter name is a loud error instead
of a silently unfiltered list.

## Trip duration rule

TripGenie applies a project-specific maximum trip duration of **366 inclusive calendar days**. `POST /api/trips` and effective `PATCH /api/trips/{tripId}` payloads that exceed that limit return the normal validation envelope, and trip detail responses refuse oversized upstream records with a dependency error instead of expanding an unbounded `days` list.

## Current concurrency note

`PATCH` flows use a read-merge-write pattern against the database API so the backend can validate effective records before forwarding partial updates. The current internal API does not expose record versions or conditional writes, so concurrent updates are still last-write-wins across services; the backend re-reads committed state after writes and the database API remains the final validation guard.
