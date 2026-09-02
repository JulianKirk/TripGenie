← Back to [README.md](../../README.md)

# Activities and Attractions Backend Service API

## Service scope

This service is the public face of Student 4's activities and attractions
microservice. Its callers are the Student 4 frontend and other backend services,
including itinerary and budget services. Neither the frontend nor another
student's service accesses the Student 4 database service directly.

The target compose address is `http://student-4-backend:8008`; examples use
`http://localhost:8008`.

```text
frontend / other students' backends
                |  :8008  /activity
                v
        student-4-backend ----------------> shared-backend :9100
                |                           /location
                |  :8009 /internal/activity
                v
        student-4-database -- SQLite
```

The Student 4 database service owns activities, their exact address details,
categories and availability schedules. The shared reference service owns
countries and cities. Student 4 stores the shared `country_id` and `city_id`,
but its public API accepts and returns their names. The backend performs that
translation over HTTP, following the existing accommodation-service convention.

The backend and database service declare independent wire schemas so they remain
independently deployable. A database response that does not satisfy the public
contract is a `502`; end-to-end contract tests must detect schema drift.

All prices in this API are non-negative numeric AUD values. Dates and times are
local to the activity's location and do not carry a timezone. Public catalogue
operations return active activities only.

### Configuration

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `http://student-4-database:8009` | Student 4 database-service base URL. |
| `DB_TIMEOUT` | `5` | Database-service timeout in seconds. |
| `LOCATION_URL` | `http://shared-backend:9100` | Shared location-service base URL. |
| `LOCATION_TIMEOUT` | `5` | Shared-service timeout in seconds. |

### Publicly writable data

This release exposes no catalogue mutation endpoints. Activities and seeded
categories are maintained through the internal database contract or seed data;
travellers, the frontend and other services only browse and search them.

### Location lookup behaviour

Country and city lists are small reference datasets. The backend may cache the
shared service's name-to-id and id-to-name mappings and refresh them after a
miss. A search naming an unknown country or city is valid and returns an empty
page. A stored location id that the shared service no longer recognises does
not make the activity disappear; the unresolved public name is omitted.

A city filter requires its country because city names are not globally unique.
The Student 4 database service never calls the shared service and never joins
the shared service's database.

### Common errors

Errors use `{"detail": "..."}`.

| Status | Meaning |
|---|---|
| `400` | Malformed, contradictory or unsupported filter. |
| `404` | Requested activity does not exist or is inactive. |
| `502` | An upstream service returned data that violates its contract. |
| `503` | The database or shared reference service is unavailable or timed out. |

`502` and `503` are retryable. An unknown location in a well-formed search is
an empty result, not an error.

## Response representations

### Activity summary

List and search operations return compact summaries:

| Field | Type | Description |
|---|---|---|
| `id` | UUID | Activity identifier. |
| `name` | string | Display name. |
| `description` | string | Activity description. |
| `price` | float | Numeric price in AUD. |
| `duration_minutes` | integer | Expected duration. |
| `minimum_age` | integer \| omitted | Inclusive minimum age when known. |
| `maximum_age` | integer \| omitted | Inclusive maximum age when known. |
| `minimum_participants` | integer | Smallest supported party. |
| `maximum_participants` | integer \| omitted | Largest supported party when known. |
| `booking_required` | boolean | Whether booking must be arranged externally. |
| `wheelchair_accessible` | boolean \| omitted | Confirmed fact; omitted means unknown. |
| `step_free_access` | boolean \| omitted | Confirmed fact; omitted means unknown. |
| `accessible_toilet` | boolean \| omitted | Confirmed fact; omitted means unknown. |
| `location_details` | object | Public country/city names and local address fields. |
| `categories` | list[string] | Stable category codes. |

Nullable facts are omitted rather than returned as JSON `null`.

### Full activity

The detail representation contains every summary field plus
`booking_notes`, `accessibility_notes` and `availability_schedules`.

Each availability schedule contains:

| Field | Type | Description |
|---|---|---|
| `id` | UUID | Schedule identifier. |
| `recurring_weekly` | boolean | Weekly rule when true; one-off date when false. |
| `day_of_week` | string \| omitted | `MONDAY` through `SUNDAY`; weekly rows only. |
| `date` | date \| omitted | ISO `YYYY-MM-DD`; one-off rows only. |
| `start_time` | time | Local `HH:MM` interval start. |
| `end_time` | time | Local `HH:MM` interval end. |

## Endpoints

## GET /health

Reports the backend and both upstream dependencies.

```bash
curl "http://localhost:8008/health"
```

```json
{
  "status": "ok",
  "service": "student-4-backend",
  "database": "ok",
  "location": "ok"
}
```

The top-level status is `degraded` when either dependency is unreachable, while
the endpoint still returns `200` because the backend itself is alive.

## GET /activity/categories

Returns the complete seeded category list in `display_order`. It exists so the
frontend and other consumers do not duplicate category labels or ordering.

```bash
curl "http://localhost:8008/activity/categories"
```

```json
{
  "categories": [
    {
      "code": "CULTURE",
      "label": "Culture",
      "description": "Museums, galleries and cultural sites",
      "display_order": 10
    },
    {
      "code": "OUTDOOR",
      "label": "Outdoor",
      "description": "Activities primarily undertaken outdoors",
      "display_order": 20
    },
    {
      "code": "TOUR",
      "label": "Tour",
      "description": "Guided or self-guided tours",
      "display_order": 30
    }
  ]
}
```

Categories are not paginated because they are a small, fixed reference list.

| Status | Meaning |
|---|---|
| `502` | Invalid database-service response. |
| `503` | Database service unavailable. |

## GET /activity/{id}

Returns one active activity with its full schedules.

| Path parameter | Type | Description |
|---|---|---|
| `id` | UUID | Activity identifier. |

```bash
curl "http://localhost:8008/activity/5ee3fe1f-62e8-4b1a-bfca-f283781c24fd"
```

```json
{
  "id": "5ee3fe1f-62e8-4b1a-bfca-f283781c24fd",
  "name": "Sydney Harbour guided walk",
  "description": "A guided walk around the harbour foreshore.",
  "price": 45.0,
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
  "location_details": {
    "country": "australia",
    "city": "sydney",
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
| `404` | Activity does not exist or is inactive. |
| `502` | Invalid upstream response. |
| `503` | Required upstream service unavailable. |

## GET /activity

Returns active activities ordered by name and then id. This is the unfiltered
equivalent of `QUERY /activity`, provided so browsers and simple consumers do
not need a request body.

| Query parameter | Type | Required | Description |
|---|---|:---:|---|
| `limit` | integer | No | Page size, 1-100; default 20. |
| `offset` | integer | No | Number of matching rows to skip; default 0. |

```bash
curl "http://localhost:8008/activity?limit=10&offset=0"
```

```json
{
  "activities": [
    {
      "id": "5ee3fe1f-62e8-4b1a-bfca-f283781c24fd",
      "name": "Sydney Harbour guided walk",
      "description": "A guided walk around the harbour foreshore.",
      "price": 45.0,
      "duration_minutes": 120,
      "minimum_age": 8,
      "minimum_participants": 1,
      "maximum_participants": 12,
      "booking_required": true,
      "wheelchair_accessible": false,
      "step_free_access": false,
      "accessible_toilet": true,
      "location_details": {
        "country": "australia",
        "city": "sydney"
      },
      "categories": ["OUTDOOR", "TOUR"]
    }
  ],
  "total": 1,
  "limit": 10,
  "offset": 0
}
```

`total` is the number of complete matches before pagination.

| Status | Meaning |
|---|---|
| `400` | Invalid `limit` or `offset`. |
| `502` | Invalid upstream response. |
| `503` | Required upstream service unavailable. |

## QUERY /activity

Performs advanced, read-only search. The HTTP `QUERY` method is safe and
idempotent like `GET`, while allowing nested filters in a JSON body. This
matches the repository's existing accommodation and shared-service contracts.

```bash
curl -X QUERY "http://localhost:8008/activity" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "harbour",
    "location": {"country": "australia", "city": "sydney"},
    "categories": {"codes": ["OUTDOOR", "TOUR"], "match": "ALL"},
    "price": {"max": 100},
    "duration_minutes": {"min": 60, "max": 180},
    "party_size": 4,
    "youngest_age": 12,
    "accessibility": {"accessible_toilet": true},
    "availability": {
      "date": "2026-10-17",
      "start_time": "09:00",
      "end_time": "14:00"
    },
    "sort": "PRICE_ASC",
    "limit": 10,
    "offset": 0
  }'
```

### Request body

All fields are optional. An empty body has the same filtering semantics as
`GET /activity`.

| Field | Type | Description |
|---|---|---|
| `text` | string | Case-insensitive substring across name and description. |
| `location` | object | Country/city names and optional street substring. |
| `categories` | object | Category codes and `ANY`/`ALL` matching. |
| `price` | range | Inclusive AUD `min` and/or `max`. |
| `duration_minutes` | range | Inclusive integer `min` and/or `max`. |
| `party_size` | integer | Match activities whose participant bounds include this value. |
| `youngest_age` | integer | Match activities whose minimum-age rule permits this age. |
| `oldest_age` | integer | Match activities whose maximum-age rule permits this age. |
| `booking_required` | boolean | Exact informational booking flag. |
| `accessibility` | object | Exact confirmed accessibility facts. |
| `availability` | object | Local date and optional usable time window. |
| `sort` | enum | Result ordering; default `NAME_ASC`. |
| `limit` | integer | Page size, 1-100; default 20. |
| `offset` | integer | Rows to skip; default 0. |

Unknown fields are rejected rather than silently ignored.

### Location filter

```json
{
  "location": {
    "country": "australia",
    "city": "sydney",
    "street": "circular"
  }
}
```

`country` and `city` are case-insensitive exact reference-name matches after
trimming. `street` is a case-insensitive substring. `city` requires `country`.
An unknown reference name returns an empty page.

### Category filter

```json
{
  "categories": {
    "codes": ["OUTDOOR", "TOUR"],
    "match": "ALL"
  }
}
```

`codes` must contain one or more unique values returned by
`GET /activity/categories`. `match` defaults to `ANY`:

- `ANY` matches an activity carrying at least one supplied category.
- `ALL` matches an activity carrying every supplied category.

An unsupported category code is a `400`; a supported code with no matching
activities produces an empty page.

### Numeric and suitability filters

Ranges use inclusive `min` and `max` values. Price values are AUD. Bounds must
be non-negative and `min` cannot exceed `max`.

`party_size` matches when:

```text
minimum_participants <= party_size
and (maximum_participants is unknown or party_size <= maximum_participants)
```

Age filters describe the actual party. `youngest_age` must satisfy the
activity's minimum-age requirement; `oldest_age` must satisfy its maximum-age
requirement. If both are supplied, `youngest_age` cannot exceed `oldest_age`.
Unknown activity bounds do not restrict a match.

### Accessibility filter

```json
{
  "accessibility": {
    "wheelchair_accessible": true,
    "step_free_access": true,
    "accessible_toilet": true
  }
}
```

Each supplied field is an exact confirmed fact. Therefore a request for `true`
does not match an activity whose value is unknown. Omitted accessibility fields
do not constrain the search.

### Availability filter

```json
{
  "availability": {
    "date": "2026-10-17",
    "start_time": "09:00",
    "end_time": "14:00"
  }
}
```

`date` is required whenever `availability` is supplied. `start_time` and
`end_time` must either both be supplied or both omitted; the start must precede
the end. All values are interpreted in the activity's local time.

A schedule applies on the requested date when either:

- it is a one-off row with that exact date; or
- it is a recurring row whose `day_of_week` matches that date's weekday.

With only `date`, any applicable schedule matches. With a requested time window,
there must be at least one possible activity start for which the entire
`duration_minutes` fits inside both the schedule interval and the requested
window. This treats a schedule equal to the duration as a fixed session and a
longer schedule as a flexible start window without another schedule-kind field.

### Sorting and pagination

Supported values are:

| Value | Ordering |
|---|---|
| `NAME_ASC` | Name ascending; default. |
| `PRICE_ASC` | Price ascending. |
| `PRICE_DESC` | Price descending. |
| `DURATION_ASC` | Duration ascending. |
| `DURATION_DESC` | Duration descending. |

Every ordering adds normalised name and activity id as deterministic tie-breaks,
so offset pages do not overlap or reshuffle unexpectedly.

### Response

The response has the same shape as `GET /activity`:

```json
{
  "activities": [],
  "total": 0,
  "limit": 20,
  "offset": 0
}
```

| Status | Meaning |
|---|---|
| `400` | Invalid field, enum, range, location pairing or time window. |
| `502` | Invalid response from the database or shared service. |
| `503` | Required upstream service unavailable. |

