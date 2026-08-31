# Student 3 database service

This FastAPI service owns the Student 3 transport SQLite database and exposes the
internal `/internal` API. No other microservice opens the SQLite file directly —
the Student 3 backend reaches this data over HTTP only.

## Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `STUDENT3_SQLITE_PATH` | `data/student-3/tripgenie.db` | SQLite database file owned by this service. |
| `STUDENT3_SEED_DATA` | `true` | Seed demo records on first start. Accepts `1/true/yes/on`. |

## Scope: plan records, not reservations

TripGenie does not book transport. A `transport_bookings` row is a **saved plan entry** —
"this transport is part of my trip". No reservation is placed with a carrier, no payment is
taken, and `estimated_cost` is a planning figure rather than an amount charged. `capacity`
and `seats_remaining` are reference data that make validation demonstrable; they are not a
statement about real inventory.

## Tables

### `transport_options`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | TEXT | Primary key, `transport_*`. Generated when omitted. |
| `type` | TEXT | `flight`, `train`, `bus`, `ferry`, `car_rental`, `transfer`. |
| `provider` | TEXT | Operator name. |
| `origin` / `destination` | TEXT | Route endpoints; filtered case-insensitively. |
| `departure_time` / `arrival_time` | TEXT | Local wall-clock `YYYY-MM-DDTHH:MM`, as printed on a ticket. |
| `departure_utc_offset` / `arrival_utc_offset` | INTEGER | Optional UTC offsets in minutes (`-720`..`+840`). Supply both or neither. |
| `duration_minutes` | INTEGER | **Derived**; never client-supplied. See below. |
| `price` | REAL | Per-traveller fare, at most 2 decimal places. |
| `capacity` | INTEGER | Total seats, `>= 1`. |
| `availability_status` | TEXT | `available`, `limited`, `sold_out`, `cancelled`. |
| `notes` | TEXT | Optional; blank strings are stored as `NULL`. |

`seats_remaining` appears in every option response but is **not** a stored
column — it is recomputed from live bookings on each read, so it can never
contradict the bookings table.

### `transport_bookings`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | TEXT | Primary key, `booking_*`. Generated when omitted. |
| `trip_id` | TEXT | Student 1 trip identifier (`trip_*`). Not a foreign key — Student 1 owns trips. |
| `transport_id` | TEXT | Foreign key to `transport_options(id)`. |
| `traveller_count` | INTEGER | `>= 1`. Named to match the Student 1 trips table. |
| `booking_date` | TEXT | `YYYY-MM-DD`; the date the entry was added to the plan. Must be on or before the departure date. |
| `estimated_cost` | REAL | Planning estimate, defaults to `price * traveller_count`; may be overridden. Never an amount charged. |
| `booking_status` | TEXT | Plan state: `pending` (shortlisted), `confirmed` (committed to the itinerary), `cancelled` (removed), `completed` (journey taken). |
| `notes` | TEXT | Optional. |

Both tables are seeded with 14 records on first start, meeting the project's
minimum of ten rows per table. Seeded `trip_id` values mirror the Student 1 seed
trips so the integrated demo shows transport attached to real trips.

## Business rules

- `duration_minutes` is always recomputed from `departure_time` and
  `arrival_time`, so it cannot drift. Journeys must be longer than zero minutes
  and at most 90 days, which leaves room for long-term car hire.
- When both UTC offsets are supplied, each end is converted to UTC before the
  duration is measured, so a leg crossing time zones reports real journey time
  rather than the gap between two clocks. Sydney 21:35 (UTC+11) to Tokyo 05:55
  (UTC+9) is 620 minutes, not the 500 the two clocks suggest. Omit the offsets
  for single-zone journeys and the local difference is used unchanged.
- Because of that, a leg may legitimately land at an earlier local clock time
  than it departed (an eastbound date-line crossing), so ordering is enforced on
  the derived duration rather than on the raw timestamps.
- `estimated_cost` defaults to the per-traveller fare total. Whole-vehicle products
  (car hire, private transfers) can override it. A `PATCH` that changes
  `traveller_count` or `transport_id` re-derives the default unless the same
  request also sends an explicit `estimated_cost`.
- Seats are counted across `pending`, `confirmed`, and `completed` bookings.
  Overselling an option returns `409 CONFLICT`; `cancelled` bookings release
  their seats. `seats_remaining` reports the same figure on every read.
- `availability_status` is operator-declared and is **not** derived from
  `seats_remaining` — an operator may close a service that still has seats, or
  hold inventory back. Consumers should show both values rather than treating
  the status as a seat count.
- New (or reactivated) bookings are refused when the option is `sold_out` or
  `cancelled`. Editing an existing booking's notes or status is still allowed, so
  historical records stay editable.
- Reducing an option's `capacity` below the seats already booked returns `422`.
- Deleting an option that still has bookings returns `409`; delete the dependent
  bookings first.

## API surface

All routes are prefixed with `/internal` and wrap responses in a `data` envelope.
Errors use the shared `{"error": {"code", "message", "details"}}` shape.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/internal/health` | Liveness plus the resolved SQLite path. |
| `GET` | `/internal/transport-options` | List and filter options. |
| `POST` | `/internal/transport-options` | Create an option. |
| `GET` | `/internal/transport-options/{transportId}` | Fetch one option. |
| `PATCH` | `/internal/transport-options/{transportId}` | Partially update an option. |
| `DELETE` | `/internal/transport-options/{transportId}` | Delete an unbooked option. |
| `GET` | `/internal/transport-options/{transportId}/bookings` | Bookings for one option. |
| `GET` | `/internal/transport-bookings` | List and filter bookings. |
| `POST` | `/internal/transport-bookings` | Create a booking. |
| `GET` | `/internal/transport-bookings/{bookingId}` | Fetch one booking. |
| `PATCH` | `/internal/transport-bookings/{bookingId}` | Partially update a booking. |
| `DELETE` | `/internal/transport-bookings/{bookingId}` | Delete a booking. |

### Filters

`GET /internal/transport-options` accepts `type`, `provider`, `origin`,
`destination`, `availability_status`, `min_price`, `max_price`, `departure_from`,
and `departure_to`. `GET /internal/transport-bookings` accepts `trip_id`,
`transport_id`, and `booking_status`. Unsupported query parameters return `400`
rather than being silently ignored, and reversed ranges (`min_price` above
`max_price`, `departure_from` after `departure_to`) return `422`.

## Status codes

| Code | Meaning |
| --- | --- |
| `400 BAD_REQUEST` | Unsupported query parameter. |
| `404 NOT_FOUND` | Unknown option or booking. |
| `409 CONFLICT` | Duplicate id, oversold capacity, or option still booked. |
| `422 VALIDATION_ERROR` | Field or business-rule validation failure. |
| `503 DATABASE_BUSY` | SQLite write lock contention; safe to retry. |

## Local checks

```bash
cd student-3
python -m pip install -e .[dev]
python -m ruff check database/student3_database_service tests/database
python -m pytest tests/database
```
