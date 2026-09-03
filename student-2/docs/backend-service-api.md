← Back to [README.md](../../README.md)

### Table of Contents

- [Service Scope](#service-scope)
- [Service Endpoints](#service-endpoints)
  - [GET /health](#get-health)
- [Accommodation Endpoints](#accommodation-endpoints)
  - [GET /accommodation/{id}](#get-accommodationid)
  - [GET /accommodation](#get-accommodation)
  - [QUERY /accommodation](#query-accommodation)
  - [POST /accommodation/ai-search](#post-accommodationai-search)
  - [POST /accommodation](#post-accommodation)
  - [PUT /accommodation/{id}](#put-accommodationid)
  - [DELETE /accommodation/{id}](#delete-accommodationid)
- [Itinerary Endpoints](#itinerary-endpoints)
  - [GET /accommodation/{id}/itineraries](#get-accommodationiditineraries)
  - [PUT /accommodation/{id}/itineraries/{itinerary_id}](#put-accommodationiditinerariesitinerary_id)
  - [DELETE /accommodation/{id}/itineraries/{itinerary_id}](#delete-accommodationiditinerariesitinerary_id)

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
      student-2-backend ──────────────▶ student-1-backend  :8001  /api
            │        │                  (itineraries)
            │        ├────────────────▶ shared-backend     :9100  /location
            │        │                  (country + city)
            │        └────────────────▶ ai-mode            :8006  /generate
            │  :9001  /internal/accommodation              (the ask box)
            ▼
      student-2-database ── SQLite
```

The three arrows to the right are the cross-service dependencies, and all are
made *here* rather than in the frontend so that the frontend keeps talking to
exactly one backend.

Adding an accommodation to an itinerary is student 1's data, so this service
does not store it; it calls student 1's public API.

Country and city are the [shared reference service](../../shared/docs/backend-service-api.md)'s
data, so this service does not store them either. The database service behind
this one keeps a `country_id` and a `city_id` on every accommodation; this
service is what turns `"australia"` into that id on a search and back into a
name on a response. Its callers never see an id, and there is exactly one list
of places in the system.

Both reference lists are small and near-static, so they are fetched once and
held in memory (`backend_service/location_client.py`), refetched when a name or
id is not in the cache. A useful side effect: once the cache is warm, requests
about places it already knows keep working while the shared service is down.
`GET /health` still reports `"location": "unreachable"`, so the outage is
visible rather than hidden. A search that names a place nobody has heard of comes
back as an empty result, not an error — nobody has accommodation in Narnia, and
that is an answer. An accommodation whose stored id the shared service does not
know still returns; its `location_details` simply omits `country`/`city`, which
beats failing a whole page over one stale reference.

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

The one message that deliberately differs is `Location`: the database service
declares `country_id`/`city_id`, this one declares `country`/`city`. That swap
is the reason this service talks to the shared reference service at all, so the
end-to-end tests assert the difference rather than the match.

ponytail: no auth. The compose network is the trust boundary for Release 0,
same as the database service. Add a shared bearer token when this service is
published beyond it.

### Configuration

| Variable       | Default                          | Purpose                                    |
|----------------|----------------------------------|--------------------------------------------|
| `DATABASE_URL` | `http://student-2-database:9001` | Base URL of the database service           |
| `DB_TIMEOUT`   | `5`                              | Seconds to wait on a database service call |
| `ITINERARY_URL` | `http://student-1-backend:8001` | Base URL of student 1's trip/itinerary service |
| `ITINERARY_PREFIX` | `/api`                      | Path prefix that service serves its API under |
| `ITINERARY_TIMEOUT` | `5`                        | Seconds to wait on an itinerary service call |
| `LOCATION_URL` | `http://shared-backend:9100`     | Base URL of the shared reference service     |
| `LOCATION_TIMEOUT` | `5`                          | Seconds to wait on a shared reference service call |
| `AI_MODE_URL`  | *(unset)*                        | Base URL of the [shared AI-Mode service](../../ai-services/ai-mode/README.md). Unset switches the ask box off |
| `AI_MODE_TIMEOUT` | `30`                          | Seconds to wait on an AI-Mode call -- a local model is slower than a database |
| `AI_MAX_ATTEMPTS` | `2`                           | How many times the model may be asked before giving up |

### Running it

```bash
docker compose up student-2-backend
```

Port `9000` is published, so the examples below work from the host. The
database service starts alongside it and stays unpublished.

### Writes

The full CRUD set is public: `POST /accommodation`, `PUT /accommodation/{id}`
and `DELETE /accommodation/{id}` alongside the reads. The page in front of this
service is where an accommodation is authored as well as browsed.

Writes speak the same public contract the reads do, which means a place is
**named**, not identified — `{"country": "australia", "city": "sydney"}`, never
an id. The route resolves the two names against the shared reference service on
the way down. A place the shared service does not know is a `400` here, unlike a
*search* for one, which is an empty result: you can ask about Narnia, you cannot
store an accommodation in it.

There is no authentication in front of any of this. Every service in this
project runs on a closed compose network and none of them authenticate; adding
it here alone would buy nothing.

### Errors

Client errors come straight from the database service, body and all: `400` for
a malformed query, `404` for a missing accommodation. Two statuses originate
here and mean the request was fine but the accommodation data could not be
reached:

| Status | Description                                                      |
|--------|------------------------------------------------------------------|
| 502    | Database service answered, but with something unusable            |
| 503    | Database service unreachable or slower than `DB_TIMEOUT`          |

The itinerary endpoints below fail the same way against student 1's service, and
so does an accommodation endpoint that has to reach the shared reference service:
a `503` when it cannot be reached, a `502` when it answers with something that
does not fit this contract. One mapping covers all three upstreams
(`backend_service/client.py`). An accommodation request only reaches the shared
service when the cache above cannot answer it, so a warm cache and a known place
are served regardless.

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
  "database": "ok",
  "location": "ok",
  "ai_mode": "ok"
}
```

`database` is whatever [`GET /health`](./database-service-api.md#get-health) on
the database service reported, and `location` the same from the
[shared reference service](../../shared/docs/backend-service-api.md#get-health);
either is `"unreachable"` if the call failed. The top-level `status` is
`"degraded"` unless both are `"ok"` — still `200`, because the service itself is
running and is what this endpoint is asked about.

`ai_mode` is the [shared AI-Mode service](../../ai-services/ai-mode/README.md),
and `"not_configured"` when `AI_MODE_URL` is unset. That one does **not** make
the service degraded: the ask box is an extra, and switching it off is a
decision rather than a fault. A configured AI-Mode that cannot be reached is.

They are reported separately because they break differently: without its
database this service serves nothing, without the shared service it serves rows
that cannot say where they are, and without AI-Mode it serves everything except
[the ask box](#post-accommodationai-search).

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

List accommodations, by name, paginated. This is the no-filter case of
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
| accommodation           | object  | Match template; see the matching rules below           |
| price_min / price_max   | float   | Bounds on `price_per_night`, inclusive                 |
| rating_min / rating_max | float   | Bounds on `rating`, inclusive                          |
| room_count_min          | integer | Minimum `room_details.room_count`                      |
| bed_count_min           | integer | Minimum `room_details.bed_count`                       |
| limit                   | integer | Max number of results, 1-100 (default 20)              |
| offset                  | integer | Number of results to skip (default 0)                  |

The [database service's QUERY](./database-service-api.md#query-internalaccommodation)
documents the template in full. Its rules hold here unchanged:

- `name` and `description` match as **case-insensitive substrings**, so a search
  box can filter on a half-typed word.
- `amenities` matches when the accommodation carries **every** amenity listed.
- Everything else matches exactly.
- `city` requires `country` — "Sydney" exists in more than one, and a city name
  cannot be resolved to a single id without knowing which. `room_details.bed_types`
  cannot be filtered on, and an unrecognised field is a `400` rather than a
  silently ignored one.
- A `country` or `city` the shared reference service does not know is an empty
  result (`{"accommodations": [], "total": 0}`), not a `400` or a `404`.
- Results come back ordered by name, so `limit`/`offset` pages do not overlap.

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

## POST /accommodation/ai-search

Search by asking. Takes a question in English, and answers with real
accommodations.

The model produces **filters and a sentence, never results**. What comes back
from it is validated as `AiSearchAnswer`: the same `AccommodationQueryRequest`
body [QUERY /accommodation](#query-accommodation) takes, plus a `reply` -- one
sentence in the traveller's own words saying what is being looked for. Then that
search runs, unchanged. So every row here came out of the database, and the worst a bad
answer can do is search for the wrong thing.

```
"good accommodation around japan under 100 a night"
        │
        ▼   POST /generate on ai-mode, with this service's own filter schema
{"accommodation": {...}, "price_max": 100, "reply": "Looking for ..."}
        │
        ▼   the ordinary QUERY /accommodation code path
   rows from student-2-database
```

The schema handed to the model is `AiSearchAnswer.model_json_schema()`
-- the contract on this page, not a copy of it -- and
[AI-Mode](../../ai-services/ai-mode/README.md) forwards it to Ollama as the
decoding `format`. Two things follow: the answer is JSON of that shape rather
than prose to be scraped, and the filter vocabulary (every field, every enum
value) has exactly one definition. Adding a filter to `schemas.py` teaches the
model about it with no prompt change.

Two things are done to that schema before it goes out, both of them measured
against `llama3.1:8b` rather than reasoned about:

- **`country` and `city` become enums** of the names the
  [shared reference service](../../shared/docs/backend-service-api.md) actually
  has, so decoding cannot produce a place with no listings. Given a free-text
  field the model answers "kyoto" for Japan and "canberra" for Australia --
  plausible, and an exact match on nothing. A city named without its country is
  not a retry either: this service holds the list that maps one to the other, so
  it fills the country in. A city two countries share (Sydney) is dropped
  instead of guessed.
- **The top-level fields are required.** Left optional, the shortest completion
  the grammar allows is `{"reply": "..."}` -- a sentence and no search at all,
  which is what "cheap things around adelaide" came back with. Required, the
  model has to decide on each filter. The fields *inside* the match template
  stay optional: required there too, it fills them with invention
  (`price_per_night: 0`, a type nobody asked for) and every one of those is an
  exact match that empties the result.

Made to answer with a bound it was not given, the model says "no bound" in
numbers: `price_min: 0`, `rating_max: 5`, and -- worse -- `price_max: 0`, a
search nothing can match. A bound outside the range where it bounds anything is
dropped before the search runs.

An answer that still does not validate is retried once (`AI_MAX_ATTEMPTS`), with
the reason it was rejected added to the prompt. Exhausted, that is a `502`.

`POST` rather than `QUERY`, unlike the search it delegates to: this one calls a
model and may retry, so it is neither safe nor idempotent -- and HTMX, which is
what the [frontend](./frontend-service.md) drives it from, cannot issue `QUERY`.

Requires `AI_MODE_URL`. Without it this endpoint is a `503` and nothing else on
this page changes.

### Request

**Method:** `POST`
**Endpoint:** `/accommodation/ai-search`
**Content-Type:** `application/json`

### Request Body

| Field  | Type    | Required | Description                                   |
|--------|---------|----------|-----------------------------------------------|
| query  | string  | Yes      | The question, 1-500 characters                |
| limit  | integer | No       | Max number of results, 1-100 (default 20)     |
| offset | integer | No       | Number of results to skip (default 0)         |

`limit` and `offset` are the caller's and are applied *after* the model has had
its say -- a pager has to keep working across an AI search, and the model is
told not to set them.

### Example Request

```bash
curl -X POST "http://localhost:9000/accommodation/ai-search" \
  -H "Content-Type: application/json" \
  -d '{"query": "good accommodation around japan under 100 a night"}'
```

### Example Response `200 OK`

The rows a [QUERY](#query-accommodation) would have returned, plus the search
that produced them.

```json
{
  "query_used": {
    "accommodation": {"location_details": {"country": "japan"}},
    "price_max": 100,
    "rating_min": 4,
    "limit": 20,
    "offset": 0
  },
  "accommodations": [
    {
      "id": "af660296-caf7-48c1-a6fe-47a8b4b69779",
      "name": "Shinjuku Capsule Hostel",
      "type": "hostel",
      "price_per_night": 38.00,
      "availability_status": "available",
      "rating": 4.0,
      "location_details": {"country": "japan", "city": "tokyo"}
    }
  ],
  "total": 1,
  "reply": "Looking for well-rated places in Japan under 100 a night."
}
```

`reply` is the model's own sentence, decoded in the same pass as the filters --
no second call, and no extra wait. It is written before any row is fetched, so
it restates the question and never describes the results.

`query_used` is an ordinary `AccommodationQueryRequest` -- `reply` is not part
of it. A caller can show what
the question was understood to mean, and re-run or edit it as a plain `QUERY`
without going near the model again -- which is exactly what the frontend's ask
box does with it.

### Error Responses

| Status | Description                                                      |
|--------|------------------------------------------------------------------|
| 400    | `query` missing, empty or over 500 characters                     |
| 502    | The model could not produce a usable search in `AI_MAX_ATTEMPTS`  |
| 502    | Bad response from the database or AI-Mode service                 |
| 503    | AI-Mode unreachable, or `AI_MODE_URL` not configured              |
| 503    | Database service unavailable                                      |

### A note on model quality

Schema-constrained decoding guarantees the answer is *well-formed*, never that
it is *right*, and the gap between those two is a model-size problem rather than
a prompt problem.

AI-Mode's own default, `qwen2.5:0.5b`, is not big enough for this. It gets the
country right every time and everything else roughly at random: "under 100 a
night" comes back as `bed_count_min: 100`, or as `price_min: 100`, and a
question with no price in it gets a price bound invented for it. Every one of
those is a filter that matches nothing, so the honest symptom is an empty
result rather than a wrong one. Rules in the prompt telling it not to do that do
not help; nor does removing the fields it misuses, which only moves the noise
next door.

`docker-compose.yml` therefore runs the service on `llama3.1:8b`, which is on
AI-Mode's approved list already. It is a `AI_MODE_DEFAULT_MODEL` change, not a
code change, and the model has to be pulled once:

```bash
docker compose exec ollama ollama pull llama3.1:8b
```

The prompt asset is shaped around the same constraint from the other side. It is
worked `Question:` / `JSON:` examples rather than instructions, because AI-Mode
calls Ollama with `raw=True` and no chat template, so the model is completing
text rather than following orders -- and it must not end on whitespace, since
AI-Mode strips that and a prompt ending on a blank line comes back as `{ }`.
Both of those are written down in `backend_service/ai_search.py`.

## POST /accommodation

Create an accommodation.

### Request

**Method:** `POST`
**Endpoint:** `/accommodation`
**Content-Type:** `application/json`

### Request Body

The accommodation message. `name`, `type`, `description`, `price_per_night`,
`availability_status` and a `location_details` carrying both `country` and
`city` are required — the database service stores the place as two non-null
ids, so neither name can be left out. Everything else is optional. An `id` is
not accepted; the database service mints it.

### Example Request

```bash
curl -X POST "http://localhost:9000/accommodation" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "example accommodation",
    "type": "hotel",
    "description": "an exemplary hotel for all your travel adventures",
    "price_per_night": 189.50,
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
  }'
```

### Example Response `201 Created`

Only what the caller needs to find the row again. The rest is what they just
sent, and `GET /accommodation/{id}` returns it in full.

```json
{
  "id": "3f1c8b52-8f8e-4a3d-9f2e-0b7c1d9a4e11",
  "name": "example accommodation"
}
```

### Error Responses

| Status | Description                                              |
|--------|----------------------------------------------------------|
| 400    | Invalid input, or a country/city the shared service has no record of |
| 502    | Database or location service answered with something unusable |
| 503    | Database or location service unreachable                 |


## PUT /accommodation/{id}

Update an accommodation.

### Request

**Method:** `PUT`
**Endpoint:** `/accommodation/{id}`
**Content-Type:** `application/json`

### Path Parameters

| Name | Type | Required | Description                     |
|------|------|----------|---------------------------------|
| id   | uuid | Yes      | Identifier of the accommodation |

### Request Body

The accommodation message with every field optional. A merge: an omitted field
keeps its stored value, and there is no way to unset one. `location_details` and
`room_details` merge field by field rather than replacing wholesale.

A `city` still requires a `country` alongside it — "Sydney" alone names more
than one place. An `id` in the body is not accepted; the path carries it.

### Example Request

```bash
curl -X PUT "http://localhost:9000/accommodation/3f1c8b52-8f8e-4a3d-9f2e-0b7c1d9a4e11" \
  -H "Content-Type: application/json" \
  -d '{
    "price_per_night": 250.00,
    "availability_status": "sold_out"
  }'
```

### Example Response `200 OK`

The whole accommodation as it now stands, place named — the same shape as
`GET /accommodation/{id}`, so a caller that has just saved needs no second read
to redraw.

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

| Status | Description                                              |
|--------|----------------------------------------------------------|
| 400    | Invalid input, a city without a country, or a place the shared service has no record of |
| 404    | Accommodation not found                                  |
| 502    | Database or location service answered with something unusable |
| 503    | Database or location service unreachable                 |


## DELETE /accommodation/{id}

Delete an accommodation.

### Request

**Method:** `DELETE`
**Endpoint:** `/accommodation/{id}`

### Path Parameters

| Name | Type | Required | Description                     |
|------|------|----------|---------------------------------|
| id   | uuid | Yes      | Identifier of the accommodation |

### Example Request

```bash
curl -X DELETE "http://localhost:9000/accommodation/3f1c8b52-8f8e-4a3d-9f2e-0b7c1d9a4e11"
```

### Example Response `204 No Content`

No body. A second call is a `404` — a delete that found nothing says so rather
than reporting success.

Any stay rows student 1 holds against this accommodation are **not** cleaned up:
they belong to that service and this one does not reach into it. See the
itinerary endpoints below.

### Error Responses

| Status | Description                                     |
|--------|-------------------------------------------------|
| 404    | Accommodation not found                         |
| 502    | Database service answered with something unusable |
| 503    | Database service unreachable                    |


## Itinerary Endpoints

Adding an accommodation to one of student 1's itineraries, and taking it off
again. The link itself is stored by student 1 — a trip holds many
accommodations and an accommodation sits on many trips — so this service owns
none of it; it relays and merges.

All three endpoints answer with the **whole** picker state rather than just the
row that changed. One response repaints the trip card, and a tick, a stay date
and the form's own bounds can never disagree with what student 1 actually stored.

```json
{
  "itineraries": [
    {
      "itinerary_id": "trip_2026_sydney_long_weekend",
      "name": "Sydney Long Weekend",
      "selected": true,
      "start_date": "2026-09-04",
      "end_date": "2026-09-07",
      "check_in": "2026-09-05",
      "check_in_time": "15:00",
      "check_out": "2026-09-06",
      "check_out_time": "10:00"
    },
    {
      "itinerary_id": "trip_2027_tokyo_spring_visit",
      "name": "Tokyo Spring Visit",
      "selected": false,
      "start_date": "2027-03-28",
      "end_date": "2027-04-04",
      "check_in": null,
      "check_in_time": null,
      "check_out": null,
      "check_out_time": null
    }
  ]
}
```

`start_date` and `end_date` are the itinerary's own window, so a caller can bound
a date input to it rather than discovering the limit from a rejection.

`check_in`/`check_out` are the stay stored against this accommodation. They are
only ever set on a `selected` itinerary, and they are read with one extra call
per selected itinerary — the reverse lookup answers *which* itineraries hold the
accommodation but returns trips, not the rows linking them. If that lookup fails
the itinerary still comes back ticked with both dates `null`: the tick is the
point and the dates are a bonus.

`selected` is whether this accommodation is already on that itinerary — what
the caller draws as ticked or unticked. It is computed from two calls to
student 1 (every itinerary, plus the reverse lookup of the ones holding this
accommodation), never one call per itinerary.

## GET /accommodation/{id}/itineraries

Every itinerary, ticked where this accommodation already sits on it.

### Path Parameters

| Name | Type | Required | Description                     |
|------|------|----------|---------------------------------|
| id   | uuid | Yes      | Identifier of the accommodation |

### Example Request

```bash
curl localhost:9000/accommodation/3f1c8b52-8f8e-4a3d-9f2e-0b7c1d9a4e11/itineraries
```

### Error Responses

| Status | Description                        |
|--------|------------------------------------|
| 404    | Malformed accommodation id         |
| 502    | Bad response from itinerary service |
| 503    | Itinerary service unavailable      |

## PUT /accommodation/{id}/itineraries/{itinerary_id}

Adds the accommodation to that itinerary and returns the repainted list.

`PUT`, not `POST`: a user clicking an already-ticked box must not get a conflict.
It replaces the pin rather than creating a second one, so re-sending the same
stay changes nothing and sending different dates **moves** it — someone
correcting the dates they just entered has to see the correction stick.

### Request Body

Optional. Without one, student 1 pins the accommodation to the itinerary's first
day with no departure recorded, which is what this endpoint did before a user
could pick the dates.

| Name        | Type   | Required | Description                                   |
|-------------|--------|----------|-----------------------------------------------|
| `check_in`       | date | No | First night. Defaults to the itinerary's start |
| `check_in_time`  | time | No | Arrival time, `HH:MM`. Omitted means none recorded |
| `check_out`      | date | No | Departure. Omitted means none recorded         |
| `check_out_time` | time | No | Departure time, `HH:MM`                        |

```json
{
  "check_in": "2026-09-05",
  "check_in_time": "15:00",
  "check_out": "2026-09-06",
  "check_out_time": "10:00"
}
```

Both dates must fall inside the itinerary's own window, `check_out` may not
precede `check_in`, and on a same-day stay `check_out_time` must be after
`check_in_time` — the times are the only thing separating arrival from
departure on one date. Student 1 owns those rules — it stores the row — so this
service relays its `422` rather than duplicating the checks.

### Path Parameters

| Name         | Type   | Required | Description                     |
|--------------|--------|----------|---------------------------------|
| id           | uuid   | Yes      | Identifier of the accommodation |
| itinerary_id | string | Yes      | Student 1's trip id             |

### Example Request

```bash
curl -X PUT localhost:9000/accommodation/3f1c8b52-8f8e-4a3d-9f2e-0b7c1d9a4e11/itineraries/trip_2026_sydney_long_weekend \
  -H 'Content-Type: application/json' \
  -d '{"check_in": "2026-09-05", "check_in_time": "15:00", "check_out": "2026-09-06"}'
```

### Error Responses

| Status | Description                        |
|--------|------------------------------------|
| 404    | Unknown itinerary, or a malformed id |
| 422    | Stay outside the itinerary, or a check-out before the check-in |
| 502    | Bad response from itinerary service |
| 503    | Itinerary service unavailable      |

## DELETE /accommodation/{id}/itineraries/{itinerary_id}

Takes the accommodation off that itinerary and returns the repainted list. The
untick half of the toggle; the same path and parameters as the `PUT`.

### Example Request

```bash
curl -X DELETE localhost:9000/accommodation/3f1c8b52-8f8e-4a3d-9f2e-0b7c1d9a4e11/itineraries/trip_2026_sydney_long_weekend
```

### Error Responses

| Status | Description                                        |
|--------|----------------------------------------------------|
| 404    | The accommodation is not on that itinerary, or a malformed id |
| 502    | Bad response from itinerary service                |
| 503    | Itinerary service unavailable                      |
