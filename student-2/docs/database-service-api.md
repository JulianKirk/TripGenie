← Back to [README.md](../../README.md)

### Table of Contents

- [Service Endpoints](#service-endpoints)
  - [GET /health](#get-health)
- [Accommodation Endpoints](#accommodation-endpoints)
  - [GET /internal/accommodation/{id}](#get-internalaccommodationid)
  - [QUERY /internal/accommodation](#query-internalaccommodation)
  - [POST /internal/accommodation](#post-internalaccommodation)
  - [PUT /internal/accommodation/{id}](#put-internalaccommodationid)

# Accommodation Database Service API

## Service Scope

This service runs on `http://student-2-database:9001`. It is internal-only --
not exposed to end users or the frontend directly. The only caller is the
backend service. The `curl` examples below use `localhost:9001`, which assumes
the service is run directly rather than inside the compose network.

ponytail: no service-to-service auth while the database service is unpublished
on the compose network and the backend is the sole caller. Add a shared bearer
token when the service gains a published port or a second caller.

### Running it

```bash
docker compose up student-2-database
```

Compose `expose`s port 9001 without publishing it, so the service is reachable
by name from other containers but not from the host. To reach it from the host
(to run the `curl` examples below), run the image directly:

```bash
docker build -f student-2/database/Dockerfile -t student-2-database student-2
docker run --rm -p 9001:9001 student-2-database
```

The SQLite database lives at `$DATABASE_URL` (default `/data/accommodation.db`
in the image, on the `student-2-db` volume). Tables are created on startup, and
an *empty* database is then filled with the starter accommodations in
`database_service/seed_data.py` — otherwise a fresh container has nothing to
serve and the frontend's list, filters and pager have nothing to show. A
database that already has rows is left alone. Set `SEED_DATA=0` to skip it
entirely; the tests do.

### Configuration

| Variable       | Default                                    | Purpose                                    |
|----------------|--------------------------------------------|--------------------------------------------|
| `DATABASE_URL` | `sqlite:///student-2/database/accommodation.db` | SQLite path (`/data/accommodation.db` in the image) |
| `SEED_DATA`    | `1`                                        | Seed an empty database on startup; `0` to skip |

### The accommodation message

There is one accommodation shape, and every field on it is nullable — the
protobuf convention. The same message is the `PUT` body, the match template
inside a `QUERY`, and the response body of every endpoint; what differs is
which fields are filled in.

Two consequences worth knowing before you write a client:

- **Responses omit what they did not set.** A field that is not populated is
  absent from the JSON rather than present as `null`. `POST` returns an
  accommodation carrying only `id` and `name`; `GET` returns one carrying
  everything. Read a missing key as "not supplied", never as "empty" -- the
  optional columns are nullable, so an omitted `rating` stays absent rather
  than being stored as `0.0`, and an explicit `0.0` or `[]` is kept as the
  real answer it is. A field the row does not carry matches no filter or
  bound.
- **`POST` is the exception that stays strict.** Create re-declares its six
  required fields, so `POST {}` is a `400` naming each one rather than a row
  with no name.

### Errors

Validation failures return `400` with FastAPI's
`{"detail": [...]}` body naming the offending fields. Missing rows return `404`.
An unrecognised field anywhere in a request body is also a `400` — no request
field is silently ignored.

## Service Endpoints

## GET /health

Liveness check. Opens a database connection and closes it — this is what CI
polls after starting the container.

### Request

**Method:** `GET`
**Endpoint:** `/health`

### Example Request

```bash
curl -X GET "http://localhost:9001/health"
```

### Example Response `200 OK`

```json
{
  "status": "ok",
  "service": "student-2-database"
}
```

Returns `200` on an empty database — it reports that the service can reach its
database, not that there is anything in it.

### Error Responses

| Status | Description                          |
|--------|--------------------------------------|
| 500    | Database could not be opened         |

## Accommodation Endpoints

## GET /internal/accommodation/{id}

Retrieve a single accommodation.

### Request

**Method:** `GET`
**Endpoint:** `/internal/accommodation/{id}`

### Path Parameters

| Name | Type | Required | Description                       |
|------|------|----------|-----------------------------------|
| id   | uuid | Yes      | Identifier of the accommodation   |

### Example Request

```bash
curl -X GET "http://localhost:9001/internal/accommodation/3f1c8b52-8f8e-4a3d-9f2e-0b7c1d9a4e11"
```

### Example Response `200 OK`

```json
{
  "id": "3f1c8b52-8f8e-4a3d-9f2e-0b7c1d9a4e11",
  "name": "example accommodation",
  "type": "hotel",
  "description": "an exemplary hotel for all your travel adventures",
  "price_per_night": 1.00,
  "availability_status": "available",
  "rating": 4.5,
  "amenities": ["wifi", "pool"],
  "location_details": {
    "country": "australia",
    "city": "sydney",
    "street": "example street avenue",
    "street_number": 123
  },
  "room_details": {
    "room_count": 3,
    "bed_count": 2,
    "bed_types": ["king", "queen"],
    "description": "three bedroom hotel space with big beds"
  }
}
```

### Error Responses

| Status | Description                |
|--------|----------------------------|
| 404    | Accommodation not found    |
| 500    | Internal server error      |


## QUERY /internal/accommodation

Search accommodations. Uses the [HTTP QUERY method](https://datatracker.ietf.org/doc/draft-ietf-httpbis-safe-method-w-body/):
safe and idempotent like `GET`, but the filters travel in a request body instead
of the query string.

### Request

**Method:** `QUERY`
**Endpoint:** `/internal/accommodation`
**Content-Type:** `application/json`

### Request Body

A query is a **match template** plus **bounds**. `accommodation` is an
accommodation message: every field you set on it must match, and every field
you leave out is not filtered on. Most fields match exactly; the three
exceptions are in the table below. The `*_min` / `*_max` fields alongside it
carry the comparisons a template cannot express.

| Field                 | Type   | Description                                                    |
|-----------------------|--------|----------------------------------------------------------------|
| accommodation         | object | Match template; see the matching rules below                   |
| price_min / price_max | float  | Bounds on `price_per_night`, inclusive                         |
| rating_min / rating_max | float | Bounds on `rating`, inclusive                                  |
| room_count_min        | integer | Minimum `room_details.room_count`                             |
| bed_count_min         | integer | Minimum `room_details.bed_count`                              |
| limit                 | integer | Max number of results, 1-100 (default 20)                     |
| offset                | integer | Number of results to skip (default 0)                         |

Inside `accommodation`, any field from [POST /internal/accommodation](#post-internalaccommodation)
can be used as a filter, including the nested `location_details` and
`room_details` objects. `city` still requires `country` — Sydney exists in more
than one.

How each field matches:

| Field                          | Matching                                                                 |
|--------------------------------|--------------------------------------------------------------------------|
| `name`, `description`          | Case-insensitive **substring**: `"har"` matches `"Harbour View Hotel"`     |
| `amenities`                    | The row must carry **every** amenity listed; an amenity matches whole, so `wifi` does not match `wifi6` |
| everything else                | Exact                                                                     |

`name` and `description` are substring matches because they are what a search
box types into, and an exact match on either is no use to someone mid-word.

`room_details.bed_types` still cannot be filtered on.

Omitting everything returns all accommodations, paginated. Results are ordered
by `name` (then `id` to break ties) — without an `ORDER BY`, `limit`/`offset`
is free to hand the same row back on two different pages.

Results are trimmed — each row carries `id`, `name`, `type`, `price_per_night`,
`availability_status`, `rating` and `location_details.country`/`city`, since a
result list is for choosing which one to `GET` in full.

### Example Request

```bash
curl -X QUERY "http://localhost:9001/internal/accommodation" \
  -H "Content-Type: application/json" \
  -d '{
    "accommodation": {
      "type": "hotel",
      "location_details": {"country": "australia", "city": "sydney"}
    },
    "price_max": 250,
    "room_count_min": 2,
    "limit": 10
  }'
```

### Example Response `200 OK`

```json
{
  "accommodations": [
    {
      "id": "3f1c8b52-8f8e-4a3d-9f2e-0b7c1d9a4e11",
      "name": "example accommodation",
      "type": "hotel",
      "price_per_night": 1.00,
      "availability_status": "available",
      "rating": 4.5,
      "location_details": {
        "country": "australia",
        "city": "sydney"
      }
    }
  ],
  "total": 1
}
```

### Error Responses

| Status | Description                                  |
|--------|----------------------------------------------|
| 400    | Unknown field / `city` given without `country` |
| 500    | Internal server error                        |


## POST /internal/accommodation

Create a new accommodation.

### Request

**Method:** `POST`
**Endpoint:** `/internal/accommodation`
**Content-Type:** `application/json`

### Request Body

| Field               | Type    | Required | Description                                                              |
|---------------------|---------|----------|--------------------------------------------------------------------------|
| name                | string  | Yes      | The name of the accommodation                                            |
| type                | enum    | Yes      | `hotel`, `hostel`, `apartment`, `resort`, `guesthouse`, `camping`        |
| description         | string  | Yes      | Free-text description of the accommodation                               |
| price_per_night     | decimal | Yes      | Price of the accommodation per night (AUD)                               |
| availability_status | enum    | Yes      | `available`, `unavailable`, `sold_out`                                   |
| rating              | float   | No       | Aggregate rating; absent until one is recorded, never `0.0` as a stand-in |
| amenities           | array   | No       | List of amenity strings                                                  |
| location_details    | object  | Yes      | Country, city, street name, and street number                            |
| room_details        | object  | No       | Room counts, bed counts, bed types, and a free-text description          |

`location_details` object:

| Field         | Type    | Required | Description                                                                       |
|---------------|---------|----------|------------------------------------------------------------------------------------|
| country       | string  | Yes      | Country name; the `Country` row is looked up or created if it doesn't exist yet    |
| city          | string  | Yes      | City name within `country`; the `City` row is looked up or created the same way    |
| street        | string  | No       | Street name                                                                        |
| street_number | integer | No       | Street number                                                                      |

`room_details` object:

| Field       | Type    | Required | Description                                                                 |
|-------------|---------|----------|-----------------------------------------------------------------------------|
| room_count  | integer | No       | Number of rooms                                                             |
| bed_count   | integer | No       | Number of beds                                                              |
| bed_types   | array   | No       | Any of `single`, `double`, `queen`, `king`, `bunk`, `sofa_bed`              |
| description | string  | No       | Free-text description of the rooms                                          |

### Example Request

```bash
curl -X POST "http://localhost:9001/internal/accommodation" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "example accommodation",
    "type": "hotel",
    "description": "an exemplary hotel for all your travel adventures",
    "price_per_night": 1.00,
    "availability_status": "available",
    "amenities": ["wifi", "pool"],
    "location_details": {
      "country": "australia",
      "city": "sydney",
      "street": "example street avenue",
      "street_number": 123
    },
    "room_details": {
      "room_count": 3,
      "bed_count": 2,
      "bed_types": ["king", "queen"],
      "description": "three bedroom hotel space with big beds"
    }
  }'
```

### Example Response `201 Created`

An accommodation message with only the fields the caller needs to find the row
again; the rest are unset and therefore absent.

```json
{
  "id": "3f1c8b52-8f8e-4a3d-9f2e-0b7c1d9a4e11",
  "name": "example accommodation"
}
```

### Error Responses

| Status | Description                      |
|--------|----------------------------------|
| 400    | Invalid input / validation error |
| 500    | Internal server error            |


## PUT /internal/accommodation/{id}

Update an existing accommodation.

### Request

**Method:** `PUT`
**Endpoint:** `/internal/accommodation/{id}`
**Content-Type:** `application/json`

### Path Parameters

| Name | Type | Required | Description                     |
|------|------|----------|---------------------------------|
| id   | uuid | Yes      | Identifier of the accommodation |

### Request Body

An accommodation message. Every field is optional here — an omitted field is
left unchanged, and sending `null` does not clear a field (there is no nullable
column behind one). Nested `location_details` and `room_details` are merged
field by field, not replaced wholesale.

### Example Request

```bash
curl -X PUT "http://localhost:9001/internal/accommodation/3f1c8b52-8f8e-4a3d-9f2e-0b7c1d9a4e11" \
  -H "Content-Type: application/json" \
  -d '{
    "price_per_night": 250.00,
    "availability_status": "sold_out"
  }'
```

### Example Response `200 OK`

The full accommodation, in the same shape as `GET /internal/accommodation/{id}` — not
just the fields that changed.

```json
{
  "id": "3f1c8b52-8f8e-4a3d-9f2e-0b7c1d9a4e11",
  "name": "example accommodation",
  "type": "hotel",
  "description": "an exemplary hotel for all your travel adventures",
  "price_per_night": 250.00,
  "availability_status": "sold_out",
  "rating": 4.5,
  "amenities": ["wifi", "pool"],
  "location_details": {
    "country": "australia",
    "city": "sydney",
    "street": "example street avenue",
    "street_number": 123
  },
  "room_details": {
    "room_count": 3,
    "bed_count": 2,
    "bed_types": ["king", "queen"],
    "description": "three bedroom hotel space with big beds"
  }
}
```

### Error Responses

| Status | Description                      |
|--------|----------------------------------|
| 400    | Invalid input / validation error |
| 404    | Accommodation not found          |
| 500    | Internal server error            |
