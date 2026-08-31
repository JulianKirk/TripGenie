← Back to [README.md](../../README.md)

### Table of Contents

- [Service Scope](#service-scope)
- [Service Endpoints](#service-endpoints)
  - [GET /health](#get-health)
- [Accommodation Endpoints](#accommodation-endpoints)
  - [GET /accommodation/{id}](#get-accommodationid)
  - [GET /accommodation](#get-accommodation)
  - [QUERY /accommodation](#query-accommodation)

# Accommodation Backend Service API

## Service Scope

This service runs on `http://student-2-backend:9000` and is the public face of
the accommodation microservice. Its callers are the frontend service and the
other students' backend services; nobody else reaches accommodation data.
The `curl` examples below use `localhost:9000`.

Every accommodation endpoint here wraps the corresponding endpoint on the
[database service](./database-service-api.md), which is internal to this
student folder and reachable only as `http://student-2-database:9001/internal/...`
on the compose network. The backend is its only caller.

```
frontend / other students' backends
            │  :9000  /accommodation
            ▼
      student-2-backend
            │  :9001  /internal/accommodation
            ▼
      student-2-database ── SQLite
```

This service declares the accommodation message itself, in
`backend/backend_service/schemas.py`, rather than importing the database
service's. It is the public face: its callers code against what it documents
and serves at `/docs`, and they cannot reach the internal service that would
otherwise own the shape. Importing it would also put the database package
inside this image, and the two would stop being independently deployable.

ponytail: the cost is a second representation of the same message. It is
bounded — only the read surface is duplicated, since `POST` and `PUT` are not
exposed — and drift is loud rather than silent: a database response that no
longer fits this service's contract is a `502`, and the end-to-end tests in
`tests/e2e/` run the real database service, so it fails CI immediately.

ponytail: no auth. The compose network is the trust boundary for Release 0,
same as the database service. Add a shared bearer token when this service is
published beyond it.

### Configuration

| Variable       | Default                          | Purpose                                    |
|----------------|----------------------------------|--------------------------------------------|
| `DATABASE_URL` | `http://student-2-database:9001` | Base URL of the database service           |
| `DB_TIMEOUT`   | `5`                              | Seconds to wait on a database service call |

### Running it

```bash
docker compose up student-2-backend
```

Port `9000` is published, so the examples below work from the host. The
database service starts alongside it and stays unpublished.

### What is not exposed

`POST` and `PUT` exist on the database service but have no public counterpart.
The accommodation service's users view and filter accommodations; they do not
author them. Add the wrappers when there is a caller that writes — they are the
same passthrough as the read endpoints.

### Errors

Client errors come straight from the database service, body and all: `400` for
a malformed query, `404` for a missing accommodation. Two statuses originate
here and mean the request was fine but the accommodation data could not be
reached:

| Status | Description                                                      |
|--------|------------------------------------------------------------------|
| 502    | Database service answered, but with something unusable            |
| 503    | Database service unreachable or slower than `DB_TIMEOUT`          |

Both carry `{"detail": "..."}`. A caller should treat them as retryable and a
`400`/`404` as not.

## Service Endpoints

## GET /health

Liveness check. Reports this service and the database service behind it, so a
caller can tell "the backend is down" from "the backend is up but its database
is not".

### Request

**Method:** `GET`
**Endpoint:** `/health`

### Example Request

```bash
curl -X GET "http://localhost:9000/health"
```

### Example Response `200 OK`

```json
{
  "status": "ok",
  "service": "student-2-backend",
  "database": "ok"
}
```

`database` is whatever [`GET /health`](./database-service-api.md#get-health) on
the database service reported, or `"unreachable"` if the call failed. The
top-level `status` is `"degraded"` in that case — still `200`, because the
service itself is running and is what this endpoint is asked about.

### Error Responses

| Status | Description           |
|--------|-----------------------|
| 500    | Internal server error |

## Accommodation Endpoints

## GET /accommodation/{id}

Retrieve a single accommodation. Wraps
[`GET /internal/accommodation/{id}`](./database-service-api.md#get-internalaccommodationid).

### Request

**Method:** `GET`
**Endpoint:** `/accommodation/{id}`

### Path Parameters

| Name | Type | Required | Description                     |
|------|------|----------|---------------------------------|
| id   | uuid | Yes      | Identifier of the accommodation |

### Example Request

```bash
curl -X GET "http://localhost:9000/accommodation/3f1c8b52-8f8e-4a3d-9f2e-0b7c1d9a4e11"
```

### Example Response `200 OK`

The full accommodation message. Fields the row does not carry are absent rather
than `null`.

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

| Status | Description                       |
|--------|-----------------------------------|
| 404    | Accommodation not found           |
| 502    | Bad response from database service |
| 503    | Database service unavailable      |

## GET /accommodation

List accommodations, newest first, paginated. This is the no-filter case of
[QUERY /accommodation](#query-accommodation) — the same call with an empty
match template — offered as a plain `GET` so a browser, a link, or an `hx-get`
can reach it without a request body.

### Request

**Method:** `GET`
**Endpoint:** `/accommodation`

### Query Parameters

| Name   | Type    | Required | Description                            |
|--------|---------|----------|----------------------------------------|
| limit  | integer | No       | Max number of results, 1-100 (default 20) |
| offset | integer | No       | Number of results to skip (default 0)  |

### Example Request

```bash
curl -X GET "http://localhost:9000/accommodation?limit=10&offset=20"
```

### Example Response `200 OK`

Trimmed rows, the same shape a `QUERY` returns — a list is for choosing which
accommodation to `GET` in full.

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

`total` is how many accommodations match in full, not how many this page
carries — it is what a pager counts against.

### Error Responses

| Status | Description                        |
|--------|------------------------------------|
| 400    | `limit` or `offset` out of range   |
| 502    | Bad response from database service |
| 503    | Database service unavailable       |

## QUERY /accommodation

Search accommodations. Wraps
[`QUERY /internal/accommodation`](./database-service-api.md#query-internalaccommodation)
and takes the identical body: a match template plus bounds, sent with the
[HTTP QUERY method](https://datatracker.ietf.org/doc/draft-ietf-httpbis-safe-method-w-body/),
which is safe and idempotent like `GET` but carries its filters in a request
body instead of the query string.

### Request

**Method:** `QUERY`
**Endpoint:** `/accommodation`
**Content-Type:** `application/json`

### Request Body

| Field                   | Type    | Description                                            |
|-------------------------|---------|--------------------------------------------------------|
| accommodation           | object  | Match template; any field set on it must match exactly |
| price_min / price_max   | float   | Bounds on `price_per_night`, inclusive                 |
| rating_min / rating_max | float   | Bounds on `rating`, inclusive                          |
| room_count_min          | integer | Minimum `room_details.room_count`                      |
| bed_count_min           | integer | Minimum `room_details.bed_count`                       |
| limit                   | integer | Max number of results, 1-100 (default 20)              |
| offset                  | integer | Number of results to skip (default 0)                  |

The [database service's QUERY](./database-service-api.md#query-internalaccommodation)
documents the template in full. Its constraints hold here unchanged: `city`
requires `country`, `amenities` and `room_details.bed_types` cannot be filtered
on, and an unrecognised field is a `400` rather than a silently ignored one.

### Example Request

```bash
curl -X QUERY "http://localhost:9000/accommodation" \
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

| Status | Description                                    |
|--------|------------------------------------------------|
| 400    | Unknown field / `city` given without `country` |
| 502    | Bad response from database service             |
| 503    | Database service unavailable                   |
