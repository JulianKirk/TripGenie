← Back to [README.md](../../README.md)

### Table of Contents

- [Service Endpoints](#service-endpoints)
  - [GET /health](#get-health)
- [Country Endpoints](#country-endpoints)
  - [GET /internal/location/country/{id}](#get-internallocationcountryid)
  - [QUERY /internal/location/country](#query-internallocationcountry)
  - [POST /internal/location/country](#post-internallocationcountry)
- [City Endpoints](#city-endpoints)
  - [GET /internal/location/city/{id}](#get-internallocationcityid)
  - [QUERY /internal/location/city](#query-internallocationcity)
  - [POST /internal/location/city](#post-internallocationcity)
- [Currency Endpoints](#currency-endpoints)
  - [GET /internal/currency/{id}](#get-internalcurrencyid)
  - [QUERY /internal/currency](#query-internalcurrency)
  - [POST /internal/currency](#post-internalcurrency)

# Shared Reference Database Service API

## Service Scope

This service runs on `http://shared-database:9101`. It is internal-only -- not
exposed to end users or any frontend directly. The only caller is the shared
backend service. The `curl` examples below use `localhost:9101`, which assumes
the service is run directly rather than inside the compose network.

ponytail: no service-to-service auth while the database service is unpublished
on the compose network and the shared backend is the sole caller. Add a shared
bearer token when the service gains a published port or a second caller.

### Running it

```bash
docker compose up shared-database
```

Compose `expose`s port 9101 without publishing it, so the service is reachable
by name from other containers but not from the host. To reach it from the host
(to run the `curl` examples below), run the image directly:

```bash
docker build -f shared/database/Dockerfile -t shared-database shared
docker run --rm -p 9101:9101 shared-database
```

The SQLite database lives at `$DATABASE_URL` (default `/data/location.db` in the
image, on the `shared-db` volume). Tables are created on startup, and an *empty*
database is then filled with the starter places, and their currencies, in
`shared_database_service/seed_data.py`.

Those rows are not demo data. Other services' seeded rows point at the ids these
names hash to, so an unseeded shared database leaves them referencing places
nothing can name. A database that already has rows is left alone. Set
`SEED_DATA=0` to skip it entirely; the tests do.

### Configuration

| Variable       | Default                              | Purpose                                            |
|----------------|--------------------------------------|----------------------------------------------------|
| `DATABASE_URL` | `sqlite:///shared/database/location.db` | SQLite path (`/data/location.db` in the image)  |
| `SEED_DATA`    | `1`                                  | Seed an empty database on startup; `0` to skip      |

### The country, city and currency messages

There is one shape per resource, and every field on each is nullable — the protobuf convention. The same message is the match template
inside a `QUERY` and the response body of every endpoint; what differs is which
fields are filled in.

Two consequences worth knowing before you write a client:

- **Responses omit what they did not set.** A field that is not populated is
  absent from the JSON rather than present as `null`. Read a missing key as "not
  supplied", never as "empty".
- **`POST` is the exception that stays strict.** Create re-declares its required
  fields, so `POST {}` is a `400` naming each one rather than a row with no name.

### Names

Names are stored normalised: trimmed and lower-cased. `"  Australia "` and
`"australia"` are the same country, and the response comes back as `"australia"`.
Presentation is the caller's business — the frontends already title-case what
they display.

### Ids

A place's id is `uuid5` over its name, so it is the same in every service that
computes it. See [object-model.md](./object-model.md#ids) for the rule and why
it exists. Two things follow for a client:

- `POST` is idempotent — the same name is always the same row.
- A caller that knows the rule can name a place without asking. That is exactly
  what `student-2/database/database_service/seed_data.py` does at startup.

### Errors

Validation failures return `400` with FastAPI's `{"detail": [...]}` body naming
the offending fields. Missing rows return `404`. An unrecognised field anywhere
in a request body is also a `400` — no request field is silently ignored.

## Service Endpoints

## GET /health

Liveness check. Opens a database connection and closes it — this is what CI
polls after starting the container.

### Request

**Method:** `GET`
**Endpoint:** `/health`

### Example Request

```bash
curl -X GET "http://localhost:9101/health"
```

### Example Response `200 OK`

```json
{
  "status": "ok",
  "service": "shared-database"
}
```

Returns `200` on an empty database — it reports that the service can reach its
database, not that there is anything in it.

### Error Responses

| Status | Description                          |
|--------|--------------------------------------|
| 500    | Database could not be opened         |

## Country Endpoints

## GET /internal/location/country/{id}

Retrieve a single country.

### Request

**Method:** `GET`
**Endpoint:** `/internal/location/country/{id}`

### Path Parameters

| Name | Type | Required | Description                |
|------|------|----------|----------------------------|
| id   | uuid | Yes      | Identifier of the country  |

### Example Request

```bash
curl -X GET "http://localhost:9101/internal/location/country/36c95358-ac43-537d-ab58-8f4123ae55c0"
```

### Example Response `200 OK`

```json
{
  "id": "36c95358-ac43-537d-ab58-8f4123ae55c0",
  "name": "australia"
}
```

### Error Responses

| Status | Description           |
|--------|-----------------------|
| 404    | Country not found     |
| 500    | Internal server error |


## QUERY /internal/location/country

Search countries. Uses the [HTTP QUERY method](https://datatracker.ietf.org/doc/draft-ietf-httpbis-safe-method-w-body/):
safe and idempotent like `GET`, but the filters travel in a request body instead
of the query string.

### Request

**Method:** `QUERY`
**Endpoint:** `/internal/location/country`
**Content-Type:** `application/json`

### Request Body

| Field   | Type    | Description                                        |
|---------|---------|----------------------------------------------------|
| country | object  | Match template; see the matching rules below       |
| limit   | integer | Max number of results, 1-100 (default 20)          |
| offset  | integer | Number of results to skip (default 0)              |

How each field inside `country` matches:

| Field  | Matching                                                                |
|--------|-------------------------------------------------------------------------|
| `name` | Case-insensitive **substring**: `"austral"` matches `"australia"`         |
| `id`   | Exact                                                                    |

`name` is a substring match because it is what a search box types into, and an
exact match is no use to someone mid-word.

Omitting everything returns all countries, paginated. Results are ordered by
`name` (then `id` to break ties) — without an `ORDER BY`, `limit`/`offset` is
free to hand the same row back on two different pages.

### Example Request

```bash
curl -X QUERY "http://localhost:9101/internal/location/country" \
  -H "Content-Type: application/json" \
  -d '{"country": {"name": "austral"}, "limit": 10}'
```

### Example Response `200 OK`

```json
{
  "countries": [
    {
      "id": "36c95358-ac43-537d-ab58-8f4123ae55c0",
      "name": "australia"
    }
  ],
  "total": 1
}
```

### Error Responses

| Status | Description           |
|--------|-----------------------|
| 400    | Unknown field         |
| 500    | Internal server error |


## POST /internal/location/country

Create a country, or look up the one that is already there.

### Request

**Method:** `POST`
**Endpoint:** `/internal/location/country`
**Content-Type:** `application/json`

### Request Body

| Field | Type   | Required | Description                                       |
|-------|--------|----------|---------------------------------------------------|
| name  | string | Yes      | Country name; trimmed and lower-cased before use   |

### Example Request

```bash
curl -X POST "http://localhost:9101/internal/location/country" \
  -H "Content-Type: application/json" \
  -d '{"name": "australia"}'
```

### Example Response `201 Created`

```json
{
  "id": "36c95358-ac43-537d-ab58-8f4123ae55c0",
  "name": "australia"
}
```

`201` when this call inserted the row, `200` when it was already there — the
caller wanted the id either way, and the id is the name, so posting the same
country twice cannot make two rows.

### Error Responses

| Status | Description                      |
|--------|----------------------------------|
| 400    | Invalid input / validation error |
| 500    | Internal server error            |

## City Endpoints

## GET /internal/location/city/{id}

Retrieve a single city.

### Request

**Method:** `GET`
**Endpoint:** `/internal/location/city/{id}`

### Path Parameters

| Name | Type | Required | Description             |
|------|------|----------|-------------------------|
| id   | uuid | Yes      | Identifier of the city  |

### Example Request

```bash
curl -X GET "http://localhost:9101/internal/location/city/96318064-7cdc-54a8-a8d8-bb2c67d12c3e"
```

### Example Response `200 OK`

```json
{
  "id": "96318064-7cdc-54a8-a8d8-bb2c67d12c3e",
  "name": "sydney",
  "country_id": "36c95358-ac43-537d-ab58-8f4123ae55c0"
}
```

### Error Responses

| Status | Description           |
|--------|-----------------------|
| 404    | City not found        |
| 500    | Internal server error |


## QUERY /internal/location/city

Search cities. Same method and same shape as the country query.

### Request

**Method:** `QUERY`
**Endpoint:** `/internal/location/city`
**Content-Type:** `application/json`

### Request Body

| Field  | Type    | Description                                       |
|--------|---------|---------------------------------------------------|
| city   | object  | Match template; see the matching rules below      |
| limit  | integer | Max number of results, 1-100 (default 20)         |
| offset | integer | Number of results to skip (default 0)             |

How each field inside `city` matches:

| Field        | Matching                                                          |
|--------------|-------------------------------------------------------------------|
| `name`       | Case-insensitive **substring**: `"syd"` matches `"sydney"`         |
| `id`         | Exact                                                              |
| `country_id` | Exact — it is an id, not something anyone types                     |

A bare `name` needs no `country_id` alongside it: this endpoint is a search, and
two Sydneys are two results, not an ambiguity. The place where a bare city name
*is* ambiguous is a caller resolving one to a single id, and that caller has the
country.

### Example Request

```bash
curl -X QUERY "http://localhost:9101/internal/location/city" \
  -H "Content-Type: application/json" \
  -d '{"city": {"country_id": "36c95358-ac43-537d-ab58-8f4123ae55c0"}, "limit": 100}'
```

### Example Response `200 OK`

```json
{
  "cities": [
    {
      "id": "96318064-7cdc-54a8-a8d8-bb2c67d12c3e",
      "name": "sydney",
      "country_id": "36c95358-ac43-537d-ab58-8f4123ae55c0"
    }
  ],
  "total": 1
}
```

### Error Responses

| Status | Description           |
|--------|-----------------------|
| 400    | Unknown field         |
| 500    | Internal server error |


## POST /internal/location/city

Create a city, or look up the one that is already there.

### Request

**Method:** `POST`
**Endpoint:** `/internal/location/city`
**Content-Type:** `application/json`

### Request Body

| Field      | Type   | Required | Description                                     |
|------------|--------|----------|-------------------------------------------------|
| name       | string | Yes      | City name; trimmed and lower-cased before use    |
| country_id | uuid   | Yes      | The country it sits in; must already exist       |

`country_id` is required because a city's id is derived from its country's name
— "sydney" alone names two places. An unknown `country_id` is a `404` here
rather than a foreign-key error further down.

### Example Request

```bash
curl -X POST "http://localhost:9101/internal/location/city" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "sydney",
    "country_id": "36c95358-ac43-537d-ab58-8f4123ae55c0"
  }'
```

### Example Response `201 Created`

```json
{
  "id": "96318064-7cdc-54a8-a8d8-bb2c67d12c3e",
  "name": "sydney",
  "country_id": "36c95358-ac43-537d-ab58-8f4123ae55c0"
}
```

`201` when this call inserted the row, `200` when it was already there — same
rule as the country endpoint.

### Error Responses

| Status | Description                      |
|--------|----------------------------------|
| 400    | Invalid input / validation error |
| 404    | Country not found                |
| 500    | Internal server error            |

## Currency Endpoints

A currency belongs to exactly one country, and a country has at most one
currency. Each carries a `conversion_rate`: how many units of it 1 AUD buys,
with the AUD row itself at `1.0`.

The seeded rates are static and indicative. They are here so a page can say
"about ¥9,800", not so anyone can be charged.

A currency belongs to exactly one country, and a country has at most one
currency. That is a deliberate simplification — France and Italy both spend
euros and get a row each. See
[object-model.md](./object-model.md#currency) for what it buys and when to undo
it.

Currencies sit under `/internal/currency`, not under `/internal/location`: a
currency is not a place, it is the other thing a country tells you.

## GET /internal/currency/{id}

Retrieve a single currency.

### Request

**Method:** `GET`
**Endpoint:** `/internal/currency/{id}`

### Path Parameters

| Name | Type | Required | Description                |
|------|------|----------|----------------------------|
| id   | uuid | Yes      | Identifier of the currency |

### Example Request

```bash
curl -X GET "http://localhost:9101/internal/currency/41348563-8656-579b-917b-088fba86759a"
```

### Example Response `200 OK`

```json
{
  "id": "41348563-8656-579b-917b-088fba86759a",
  "name": "australian dollar",
  "code": "AUD",
  "symbol": "$",
  "conversion_rate": 1.0,
  "country_id": "36c95358-ac43-537d-ab58-8f4123ae55c0"
}
```

### Error Responses

| Status | Description           |
|--------|-----------------------|
| 404    | Currency not found    |
| 500    | Internal server error |


## QUERY /internal/currency

Search currencies. Same method and same shape as the country and city queries.

### Request

**Method:** `QUERY`
**Endpoint:** `/internal/currency`
**Content-Type:** `application/json`

### Request Body

| Field    | Type    | Description                                       |
|----------|---------|---------------------------------------------------|
| currency | object  | Match template; see the matching rules below      |
| limit    | integer | Max number of results, 1-100 (default 20)         |
| offset   | integer | Number of results to skip (default 0)             |

How each field inside `currency` matches:

| Field        | Matching                                                                |
|--------------|-------------------------------------------------------------------------|
| `name`       | Case-insensitive **substring**: `"dollar"` matches `"australian dollar"`  |
| `id`         | Exact                                                                    |
| `country_id` | Exact — this is the usual filter: "what does this country spend"          |
| `code`       | Exact, case-insensitive: `"eur"` matches `"EUR"`                          |
| `symbol`     | Exact — a symbol is one or two characters, so a substring match is noise  |
| `conversion_rate`   | **Not filterable** — see below                                            |

`code` is not unique, so filtering on it answers "who spends this" and can return
several countries: `{"currency": {"code": "EUR"}}` matches both France and Italy.

`conversion_rate` cannot be filtered on. Exact equality against a float never
matches what anyone meant, and nobody searches for "the currency at exactly
98.0". Add `conversion_rate_min`/`conversion_rate_max` alongside the template if
a range ever has a caller.

### Example Request

```bash
curl -X QUERY "http://localhost:9101/internal/currency" \
  -H "Content-Type: application/json" \
  -d '{"currency": {"country_id": "36c95358-ac43-537d-ab58-8f4123ae55c0"}}'
```

### Example Response `200 OK`

```json
{
  "currencies": [
    {
      "id": "41348563-8656-579b-917b-088fba86759a",
      "name": "australian dollar",
      "code": "AUD",
      "symbol": "$",
      "conversion_rate": 1.0,
      "country_id": "36c95358-ac43-537d-ab58-8f4123ae55c0"
    }
  ],
  "total": 1
}
```

### Error Responses

| Status | Description           |
|--------|-----------------------|
| 400    | Unknown field         |
| 500    | Internal server error |


## POST /internal/currency

Give a country its currency, or look up the one it already has.

### Request

**Method:** `POST`
**Endpoint:** `/internal/currency`
**Content-Type:** `application/json`

### Request Body

| Field      | Type   | Required | Description                                          |
|------------|--------|----------|------------------------------------------------------|
| name       | string | Yes      | Currency name; trimmed and lower-cased before use     |
| code       | string | Yes      | ISO 4217, exactly three characters; upper-cased before use |
| symbol     | string | Yes      | What a page renders next to a number: `$`, `¥`, `€` |
| conversion_rate   | float  | Yes      | How many units of this currency 1 AUD buys; must be > 0 |
| country_id | uuid   | Yes      | The country that spends it; must already exist        |

`country_id` is required because a currency's id is derived from its country's
name, and because the country is what a caller actually has in hand. An unknown
`country_id` is a `404`.

### Example Request

```bash
curl -X POST "http://localhost:9101/internal/currency" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "australian dollar",
    "code": "AUD",
    "symbol": "$",
    "conversion_rate": 1.0,
    "country_id": "36c95358-ac43-537d-ab58-8f4123ae55c0"
  }'
```

### Example Response `201 Created`

```json
{
  "id": "41348563-8656-579b-917b-088fba86759a",
  "name": "australian dollar",
  "code": "AUD",
  "symbol": "$",
  "conversion_rate": 1.0,
  "country_id": "36c95358-ac43-537d-ab58-8f4123ae55c0"
}
```

`201` when this call inserted the row, `200` when it was already there — same
rule as the place endpoints. An existing row comes back untouched — code, symbol
and rate included: this is get-or-create, not an update, so a stale rate cannot
be refreshed through it. That endpoint does not exist yet.

Giving a country a **second** currency is a `409`. The one-to-one is a `UNIQUE`
constraint underneath, so this check is what turns it into an answer rather than
a 500 out of SQLite.

### Error Responses

| Status | Description                          |
|--------|--------------------------------------|
| 400    | Invalid input / validation error     |
| 404    | Country not found                    |
| 409    | Country already has a currency       |
| 500    | Internal server error                |
