← Back to [README.md](../../README.md)

# Activities and Attractions Database Service API

## Service scope

This internal FastAPI service is the only process that opens the Student 4
SQLite database. The Student 4 backend is its only caller. The frontend, shared
reference service and other students' services never call it directly.

The target compose address is `http://student-4-database:8009`. Examples use
`http://localhost:8009` for a database service run directly on the host.

```text
student-4-backend
        |  :8009 /internal/activity
        v
student-4-database -- SQLite
```

The service stores shared country and city UUIDs without resolving them. It
makes no outbound HTTP calls and never opens another service's database. The
[public backend](./backend-service-api.md) translates public place names to
these identifiers before querying and translates identifiers back to names in
responses.

### Configuration

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `sqlite:///student-4/database/activities.db` | SQLAlchemy SQLite URL. |
| `SEED_DATA` | `1` | Seed ten categories and ten activities into an empty catalogue; set to `0` in isolated tests. |

The eventual container path and volume may override `DATABASE_URL` without
changing this API contract.

## Persistence rules

Money is represented by Python `Decimal`, limited to two fractional digits,
and stored in SQLite as canonical text such as `"45.00"`. API requests and
responses also use canonical decimal strings. Application arithmetic never
uses binary floating point. Price filtering and sorting compare integer-part
length and then canonical lexical value, preserving exact order without a
floating-point conversion.

Activity writes are aggregate operations. The activity, location, category
associations and schedules are validated together and committed in one
transaction. A failed validation or database operation leaves the previous
aggregate unchanged.

Deleting an activity is a hard deletion. Its location, category associations
and schedules are deleted in the same transaction through cascading foreign
keys. Categories themselves remain because they are shared seeded reference
rows.

## Common errors

Errors use `{"detail": "..."}`. Validation handlers convert framework-level
request validation failures to the status codes below.

| Status | Meaning |
|---|---|
| `400` | Malformed input, unknown field, invalid invariant, unsupported category or contradictory query. |
| `404` | Activity does not exist. |
| `500` | SQLite could not be opened or a database operation failed unexpectedly. |

## Wire representations

Unknown fields are rejected in every request and response schema.

### PricingBasis

| Value | Meaning | Estimated party total |
|---|---|---|
| `PER_PERSON` | The provider publishes a price for one traveller. This is used whenever a per-person price is available. | `price * party_size` |
| `FLAT_ADMISSION` | The provider offers only one flat admission charge covering the admitted party. | `price` |

Price filters compare the listed `price`, not the estimated party total.

### Activity write

`POST` and `PUT` accept the same complete aggregate shape:

| Field | Type | Required | Rules |
|---|---|:---:|---|
| `name` | string | Yes | Non-empty after trimming. |
| `description` | string | Yes | Non-empty after trimming. |
| `price` | decimal string | Yes | Canonical non-negative AUD value with two fractional digits. |
| `pricing_basis` | PricingBasis | Yes | `PER_PERSON` or `FLAT_ADMISSION`. |
| `duration_minutes` | integer | Yes | Greater than zero. |
| `minimum_age` | integer \| null | No | Non-negative when present. |
| `maximum_age` | integer \| null | No | At least `minimum_age` when both are present. |
| `minimum_participants` | integer | Yes | At least 1. |
| `maximum_participants` | integer \| null | No | At least `minimum_participants` when present. |
| `booking_required` | boolean | No | Defaults to `false`. |
| `booking_notes` | string \| null | No | Informational external-booking guidance. |
| `wheelchair_accessible` | boolean \| null | No | `null` means unknown. |
| `step_free_access` | boolean \| null | No | `null` means unknown. |
| `accessible_toilet` | boolean \| null | No | `null` means unknown. |
| `accessibility_notes` | string \| null | No | Additional non-filterable detail. |
| `is_active` | boolean | No | Defaults to `true`. |
| `location_details` | object | Yes | Shared place IDs and locally owned address fields. |
| `categories` | list[string] | Yes | One or more unique seeded category codes. |
| `availability_schedules` | list[object] | Yes | May be empty only when `is_active` is `false`. |

`location_details` has this write shape:

| Field | Type | Required | Rules |
|---|---|:---:|---|
| `country_id` | UUID | Yes | External shared Country reference. |
| `city_id` | UUID | Yes | External shared City reference. |
| `street` | string \| null | No | Optional address text. |
| `street_number` | integer \| null | No | Optional street number. |

Each `availability_schedules` entry has this write shape:

| Field | Type | Required | Rules |
|---|---|:---:|---|
| `recurring_weekly` | boolean | Yes | Selects the weekly or one-off representation. |
| `day_of_week` | string \| null | Conditional | Required for weekly rows and forbidden otherwise. |
| `date` | date \| null | Conditional | Required for one-off rows and forbidden otherwise. |
| `start_time` | time | Yes | Local `HH:MM`; must precede `end_time`. |
| `end_time` | time | Yes | Local `HH:MM`; no overnight intervals. |

Every interval must be at least `duration_minutes` long, and the aggregate may
not contain duplicate schedules. `day_of_week` is one of `MONDAY` through
`SUNDAY`.

### Activity record

An activity record contains every activity-write field plus generated IDs:

- top-level `id` is the activity UUID;
- `location_details.id` is the location UUID; and
- every availability schedule has its own `id`.

Child IDs are internal persistence details. The backend omits the location and
schedule IDs from its public representation.

Nullable fields are omitted from responses rather than returned as JSON
`null`. Arrays are always present. The database service returns shared
`country_id` and `city_id`; it never returns public country or city names.

### Activity summary

Query results omit booking/accessibility notes and schedules, but retain the
fields required by the public catalogue:

- activity ID, name and description;
- exact price and pricing basis;
- duration, age and participant bounds;
- booking and accessibility facts;
- `is_active`;
- location details with shared IDs; and
- category codes.

### Category

| Field | Type | Description |
|---|---|---|
| `code` | string | Stable enum-compatible primary key. |
| `label` | string | Human-readable label. |
| `description` | string \| omitted | Optional explanation. |
| `display_order` | integer | Non-negative selector order. |

Categories are fixed seed data. This release has no category mutation
endpoints.

## Endpoints

## GET /internal/health

Opens and closes a database connection.

```bash
curl "http://localhost:8009/internal/health"
```

```json
{
  "status": "ok",
  "service": "student-4-database"
}
```

An empty catalogue is healthy. Failure to open SQLite returns `500`.

## GET /internal/activity/categories

Returns every seeded category ordered by `display_order`, then `code`.

```bash
curl "http://localhost:8009/internal/activity/categories"
```

```json
{
  "categories": [
    {
      "code": "OUTDOOR",
      "label": "Outdoor",
      "description": "Activities primarily undertaken outdoors",
      "display_order": 60
    }
  ]
}
```

The categories route is registered before the UUID detail route so the literal
word `categories` cannot be interpreted as an activity identifier.

The repository includes a populated development database at
`student-4/database/activities.db`. It contains at least ten rows in each
Student 4 table for assignment inspection. Runtime seeding is idempotent and
does not replace an activity catalogue after it contains data.

## GET /internal/activity/{id}

Returns one full activity record, whether active or inactive.

```bash
curl "http://localhost:8009/internal/activity/5ee3fe1f-62e8-4b1a-bfca-f283781c24fd"
```

```json
{
  "id": "5ee3fe1f-62e8-4b1a-bfca-f283781c24fd",
  "name": "Sydney Harbour guided walk",
  "description": "A guided walk around the harbour foreshore.",
  "price": "45.00",
  "pricing_basis": "PER_PERSON",
  "duration_minutes": 120,
  "minimum_age": 8,
  "minimum_participants": 1,
  "maximum_participants": 12,
  "booking_required": true,
  "booking_notes": "Arrange with the operator at least 24 hours ahead.",
  "wheelchair_accessible": false,
  "step_free_access": false,
  "accessible_toilet": true,
  "accessibility_notes": "Some sections contain steep paths.",
  "is_active": true,
  "location_details": {
    "id": "18de66f9-6faa-41c3-a4f1-6b1907dd1630",
    "country_id": "36c95358-ac43-537d-ab58-8f4123ae55c0",
    "city_id": "96318064-7cdc-54a8-a8d8-bb2c67d12c3e",
    "street": "circular quay"
  },
  "categories": ["OUTDOOR", "TOUR"],
  "availability_schedules": [
    {
      "id": "80b4431a-fee9-48c8-953a-b256e4df43cd",
      "recurring_weekly": true,
      "day_of_week": "SATURDAY",
      "start_time": "09:00",
      "end_time": "11:00"
    }
  ]
}
```

| Status | Meaning |
|---|---|
| `404` | Activity does not exist. |

## QUERY /internal/activity

Searches activity records using shared location IDs. The public backend calls
this endpoint after translating place names. The HTTP `QUERY` method is safe
and idempotent like `GET` while allowing nested JSON filters.

All request fields are optional. An empty body returns active and inactive
records together, paginated. The public backend always sends
`"is_active": true`.

| Field | Type | Description |
|---|---|---|
| `text` | string | Case-insensitive substring across name and description. |
| `location_details` | object | Exact `country_id`/`city_id` and optional case-insensitive street substring. |
| `categories` | object | Unique seeded `codes` plus `ANY` or `ALL` matching. |
| `price` | decimal range | Inclusive listed-price `min` and/or `max` strings. |
| `duration_minutes` | integer range | Inclusive `min` and/or `max`. |
| `party_size` | integer | Match participant bounds. |
| `youngest_age` | integer | Match the minimum-age rule. |
| `oldest_age` | integer | Match the maximum-age rule. |
| `booking_required` | boolean | Exact match. |
| `accessibility` | object | Exact nullable accessibility facts. |
| `availability` | object | Required local `date` and optional complete time window. |
| `is_active` | boolean | Exact lifecycle-state match. |
| `sort` | enum | `NAME_ASC`, `PRICE_ASC`, `PRICE_DESC`, `DURATION_ASC` or `DURATION_DESC`. |
| `limit` | integer | Page size, 1-100; default 20. |
| `offset` | integer | Rows to skip; default 0. |

A `city_id` does not require `country_id` internally because a shared city UUID
already identifies one city in one country. Category, suitability,
accessibility and availability matching follow the public API rules exactly.
Unsupported category codes and contradictory ranges return `400`.

```bash
curl -X QUERY "http://localhost:8009/internal/activity" \
  -H "Content-Type: application/json" \
  -d '{
    "location_details": {
      "country_id": "36c95358-ac43-537d-ab58-8f4123ae55c0",
      "city_id": "96318064-7cdc-54a8-a8d8-bb2c67d12c3e"
    },
    "categories": {"codes": ["OUTDOOR"], "match": "ANY"},
    "price": {"max": "100.00"},
    "party_size": 4,
    "is_active": true,
    "limit": 10,
    "offset": 0
  }'
```

```json
{
  "activities": [
    {
      "id": "5ee3fe1f-62e8-4b1a-bfca-f283781c24fd",
      "name": "Sydney Harbour guided walk",
      "description": "A guided walk around the harbour foreshore.",
      "price": "45.00",
      "pricing_basis": "PER_PERSON",
      "duration_minutes": 120,
      "minimum_age": 8,
      "minimum_participants": 1,
      "maximum_participants": 12,
      "booking_required": true,
      "wheelchair_accessible": false,
      "step_free_access": false,
      "accessible_toilet": true,
      "is_active": true,
      "location_details": {
        "country_id": "36c95358-ac43-537d-ab58-8f4123ae55c0",
        "city_id": "96318064-7cdc-54a8-a8d8-bb2c67d12c3e"
      },
      "categories": ["OUTDOOR", "TOUR"]
    }
  ],
  "total": 1,
  "limit": 10,
  "offset": 0
}
```

`total` counts complete matches before pagination. Ordering always adds
normalized name and activity ID as deterministic tie-breakers.

## POST /internal/activity

Creates one activity aggregate. The service generates the activity, location
and schedule UUIDs. The request body is the complete
[activity-write representation](#activity-write).

```bash
curl -X POST "http://localhost:8009/internal/activity" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Sydney Harbour guided walk",
    "description": "A guided walk around the harbour foreshore.",
    "price": "45.00",
    "pricing_basis": "PER_PERSON",
    "duration_minutes": 120,
    "minimum_age": 8,
    "minimum_participants": 1,
    "maximum_participants": 12,
    "booking_required": true,
    "is_active": true,
    "location_details": {
      "country_id": "36c95358-ac43-537d-ab58-8f4123ae55c0",
      "city_id": "96318064-7cdc-54a8-a8d8-bb2c67d12c3e",
      "street": "circular quay"
    },
    "categories": ["OUTDOOR", "TOUR"],
    "availability_schedules": [
      {
        "recurring_weekly": true,
        "day_of_week": "SATURDAY",
        "start_time": "09:00",
        "end_time": "11:00"
      }
    ]
  }'
```

Success returns `201 Created` with the full activity record.

## PUT /internal/activity/{id}

Replaces an existing activity aggregate while preserving its activity UUID.
The request body is the complete activity-write representation; omitted
required fields are validation errors rather than partial updates.

Location data is updated in place. Category associations and schedules are
replaced by the submitted lists in the same transaction. Replacement schedules
receive new UUIDs because schedule identifiers are internal persistence details,
not public booking identifiers.

```bash
curl -X PUT "http://localhost:8009/internal/activity/5ee3fe1f-62e8-4b1a-bfca-f283781c24fd" \
  -H "Content-Type: application/json" \
  --data @activity.json
```

Success returns `200 OK` with the full replacement record.

| Status | Meaning |
|---|---|
| `400` | Replacement aggregate is invalid. |
| `404` | Activity does not exist. |

## DELETE /internal/activity/{id}

Permanently deletes the activity and all locally owned children.

```bash
curl -X DELETE "http://localhost:8009/internal/activity/5ee3fe1f-62e8-4b1a-bfca-f283781c24fd"
```

```json
{
  "id": "5ee3fe1f-62e8-4b1a-bfca-f283781c24fd",
  "deleted": true
}
```

| Status | Meaning |
|---|---|
| `404` | Activity does not exist. |

## Transactional invariants

The database service checks the effective aggregate before `POST` or `PUT`
commits:

- the price is canonical, non-negative and has exactly two decimal places;
- the pricing basis is supported;
- age and participant bounds are ordered;
- category codes are supported, unique and non-empty;
- the recurrence discriminator on every schedule is valid;
- schedule intervals are unique, same-day and at least the activity duration;
- an active activity has at least one schedule; and
- the location, category associations and schedules all belong to the activity
  being written.

SQLite foreign keys and checks enforce row-local constraints as a final guard.
Cross-row rules are evaluated by the service inside the same transaction as the
write. There are no partial aggregate writes and no soft-delete state beyond
the explicitly writable `is_active` catalogue flag.
