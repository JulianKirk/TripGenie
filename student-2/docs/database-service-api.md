← Back to [README.md](../../README.md)

### Table of Contents

- [Service Endpoints](#service-endpoints)
  - [GET /health](#get-health)
- [Accommodation Endpoints](#accommodation-endpoints)
  - [GET /accommodation/{id}](#get-accommodationid)
  - [QUERY /accommodation](#query-accommodation)
  - [POST /accommodation](#post-accommodation)
  - [PUT /accommodation/{id}](#put-accommodationid)

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
in the image, on the `student-2-db` volume). Tables are created on startup;
there is no seed data.

### Errors

Validation failures return `400` with FastAPI's
`{"detail": [...]}` body naming the offending fields. Missing rows return `404`.

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

## GET /accommodation/{id}

Retrieve a single accommodation.

### Request

**Method:** `GET`
**Endpoint:** `/accommodation/{id}`

### Path Parameters

| Name | Type | Required | Description                       |
|------|------|----------|-----------------------------------|
| id   | uuid | Yes      | Identifier of the accommodation   |

### Example Request

```bash
curl -X GET "http://localhost:9001/accommodation/3f1c8b52-8f8e-4a3d-9f2e-0b7c1d9a4e11"
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


## QUERY /accommodation

Search accommodations. Uses the [HTTP QUERY method](https://datatracker.ietf.org/doc/draft-ietf-httpbis-safe-method-w-body/):
safe and idempotent like `GET`, but the filters travel in a request body instead
of the query string.

### Request

**Method:** `QUERY`
**Endpoint:** `/accommodation`
**Content-Type:** `application/json`

### Request Body

| Field          | Type    | Required | Default | Description                                                   |
|----------------|---------|----------|---------|---------------------------------------------------------------|
| city           | string  | No       | —       | Match accommodations in this city; requires `country`         |
| country        | string  | No       | —       | Match accommodations in this country                          |
| min_room_count | integer | No       | —       | Only accommodations whose room details meet this room count   |
| limit          | integer | No       | 20      | Max number of results, 1-100                                  |
| offset         | integer | No       | 0       | Number of results to skip                                     |

Omitting every filter returns all accommodations, paginated.

### Example Request

```bash
curl -X QUERY "http://localhost:9001/accommodation" \
  -H "Content-Type: application/json" \
  -d '{
    "city": "sydney",
    "country": "australia",
    "min_room_count": 2,
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
| 400    | Invalid filter / `city` given without `country` |
| 500    | Internal server error                        |


## POST /accommodation

Create a new accommodation.

### Request

**Method:** `POST`
**Endpoint:** `/accommodation`
**Content-Type:** `application/json`

### Request Body

| Field               | Type    | Required | Description                                                              |
|---------------------|---------|----------|--------------------------------------------------------------------------|
| name                | string  | Yes      | The name of the accommodation                                            |
| type                | enum    | Yes      | `hotel`, `hostel`, `apartment`, `resort`, `guesthouse`, `camping`        |
| description         | string  | Yes      | Free-text description of the accommodation                               |
| price_per_night     | decimal | Yes      | Price of the accommodation per night (AUD)                               |
| availability_status | enum    | Yes      | `available`, `unavailable`, `sold_out`                                   |
| rating              | float   | No       | Aggregate rating, defaults to `0.0`                                      |
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
| room_count  | integer | Yes      | Number of rooms                                                             |
| bed_count   | integer | Yes      | Number of beds                                                              |
| bed_types   | array   | No       | Any of `single`, `double`, `queen`, `king`, `bunk`, `sofa_bed`              |
| description | string  | No       | Free-text description of the rooms                                          |

### Example Request

```bash
curl -X POST "http://localhost:9001/accommodation" \
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


## PUT /accommodation/{id}

Update an existing accommodation.

### Request

**Method:** `PUT`
**Endpoint:** `/accommodation/{id}`
**Content-Type:** `application/json`

### Path Parameters

| Name | Type | Required | Description                     |
|------|------|----------|---------------------------------|
| id   | uuid | Yes      | Identifier of the accommodation |

### Request Body

Same fields as `POST /accommodation`, minus `id`. Omitted fields are left unchanged.

### Example Request

```bash
curl -X PUT "http://localhost:9001/accommodation/3f1c8b52-8f8e-4a3d-9f2e-0b7c1d9a4e11" \
  -H "Content-Type: application/json" \
  -d '{
    "price_per_night": 250.00,
    "availability_status": "sold_out"
  }'
```

### Example Response `200 OK`

The full accommodation, in the same shape as `GET /accommodation/{id}` — not
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
