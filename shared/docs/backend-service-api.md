← Back to [README.md](../../README.md)

### Table of Contents

- [Service Scope](#service-scope)
- [Service Endpoints](#service-endpoints)
  - [GET /health](#get-health)
- [Country Endpoints](#country-endpoints)
  - [GET /location/country/{id}](#get-locationcountryid)
  - [GET /location/country](#get-locationcountry)
  - [QUERY /location/country](#query-locationcountry)
- [City Endpoints](#city-endpoints)
  - [GET /location/city/{id}](#get-locationcityid)
  - [GET /location/city](#get-locationcity)
  - [QUERY /location/city](#query-locationcity)
- [Currency Endpoints](#currency-endpoints)
  - [GET /currency/country](#get-currencycountry)
  - [GET /currency/{id}](#get-currencyid)
  - [GET /currency](#get-currency)
  - [QUERY /currency](#query-currency)

# Shared Reference Backend Service API

## Service Scope

This service runs on `http://shared-backend:9100` and is the public face of the
shared reference microservice. Its callers are the other students' backend
services; nobody else reaches reference data. The `curl` examples below use
`localhost:9100`.

Every endpoint here wraps the corresponding endpoint on the
[database service](./database-service-api.md), which is internal to this folder
and reachable only as `http://shared-database:9101/internal/...` on the compose
network. The backend is its only caller.

```
other students' backends
            │  :9100  /location, /currency
            ▼
      shared-backend
            │  :9101  /internal/location, /internal/currency
            ▼
      shared-database ── SQLite
```

Currencies sit under their own prefix rather than under `/location`: a currency
is not a place, it is the other thing a country tells you.

This service declares the country, city and currency messages itself, in
`backend/shared_backend_service/schemas.py`, rather than importing the database
service's. It is the public face: its callers code against what it documents and
serves at `/docs`, and they cannot reach the internal service that would
otherwise own the shape. Importing it would also put the database package inside
this image, and the two would stop being independently deployable.

ponytail: the cost is a second representation of the same message. It is
bounded — only the read surface is duplicated, since `POST` is not exposed — and
drift is loud rather than silent: a database response that no longer fits this
service's contract is a `502`, and the end-to-end tests in `tests/e2e/` run the
real database service, so it fails CI immediately.

ponytail: no auth. The compose network is the trust boundary for Release 0, same
as the database service. Add a shared bearer token when this service is
published beyond it.

### Configuration

| Variable       | Default                        | Purpose                                    |
|----------------|--------------------------------|--------------------------------------------|
| `DATABASE_URL` | `http://shared-database:9101`  | Base URL of the database service           |
| `DB_TIMEOUT`   | `5`                            | Seconds to wait on a database service call |

### Running it

```bash
docker compose up shared-backend
```

Port `9100` is published, so the examples below work from the host. The database
service starts alongside it and stays unpublished.

### What is not exposed

`POST` exists on the database service but has no public counterpart. The
reference lists are seeded, and a service that lets any caller invent countries
on demand is a service that quietly accumulates typos and near-duplicates. Add
the wrapper when there is a caller that genuinely needs to add a place — it is
the same passthrough as the read endpoints.

### How to use this service

The pattern every caller follows: **store the id, publish the name.** A service
that stores a place keeps the country and city ids on its own row and asks this
service to turn a name into an id on the way in and back into a name on the way
out. Its own public contract goes on speaking names, and there is exactly one
list of places in the system.

The two `GET` list endpoints are what that costs in practice. Both lists are
small and near-static, so a caller pages through them once and keeps a
name-to-id map in memory — see
`student-2/backend/backend_service/location_client.py` for a worked example,
including what to do on a miss.

### Currencies

A currency belongs to exactly one country, and a country has at most one
currency — so a service that shows a price needs nothing but the country id it
already stores. See [object-model.md](./object-model.md#currency) for why that
one-to-one is deliberate and when to undo it.

A currency carries a `name`, an ISO 4217 `code` (`AUD`, `JPY`, `EUR`), a
`symbol`, and a `conversion_rate` — how many units of it 1 AUD buys. TripGenie
quotes prices in AUD, so AUD is the base and its own row is exactly `1.0`;
converting is one multiplication with no special case for home.

The rates are static and indicative, enough for a page to say "about ¥9,800" and
not enough to charge anyone. There is no endpoint that refreshes one.

[`GET /currency/country`](#get-currencycountry) is the shortcut for what a
caller would otherwise do in two requests: find the country, then find its
currency.

A code is **not** unique — France's euro and Italy's euro are two rows and both
are `EUR`, so a code names a currency rather than a row. Asking by code is
therefore [QUERY /currency](#query-currency), which answers with a list, not the
single-answer endpoint above.

### Names

Names are stored and returned normalised: trimmed and lower-cased. Match on the
normalised form; title-case for display at the edge, the way the frontends
already do.

### Errors

Client errors come straight from the database service, body and all: `400` for a
malformed query, `404` for a missing place. Two statuses originate here and mean
the request was fine but the reference data could not be reached:

| Status | Description                                              |
|--------|----------------------------------------------------------|
| 502    | Database service answered, but with something unusable    |
| 503    | Database service unreachable or slower than `DB_TIMEOUT`  |

Both carry `{"detail": "..."}`. A caller should treat them as retryable and a
`400`/`404` as not.

## Service Endpoints

## GET /health

Liveness check. Reports this service and the database service behind it, so a
caller can tell "the shared service is down" from "it is up but its database is
not".

### Request

**Method:** `GET`
**Endpoint:** `/health`

### Example Request

```bash
curl -X GET "http://localhost:9100/health"
```

### Example Response `200 OK`

```json
{
  "status": "ok",
  "service": "shared-backend",
  "database": "ok"
}
```

`status` is `degraded` and `database` is `unreachable` when the database service
cannot be reached — still a `200`, because the question this endpoint answers is
whether *this* service is running, and it is.

### Error Responses

| Status | Description           |
|--------|-----------------------|
| 500    | Internal server error |

## Country Endpoints

## GET /location/country/{id}

Retrieve a single country.

### Request

**Method:** `GET`
**Endpoint:** `/location/country/{id}`

### Path Parameters

| Name | Type | Required | Description               |
|------|------|----------|---------------------------|
| id   | uuid | Yes      | Identifier of the country |

### Example Request

```bash
curl -X GET "http://localhost:9100/location/country/36c95358-ac43-537d-ab58-8f4123ae55c0"
```

### Example Response `200 OK`

```json
{
  "id": "36c95358-ac43-537d-ab58-8f4123ae55c0",
  "name": "australia"
}
```

### Error Responses

| Status | Description                        |
|--------|------------------------------------|
| 404    | Country not found                  |
| 502    | Bad response from database service |
| 503    | Database service unavailable       |


## GET /location/country

Every country, paginated. The no-filter
[QUERY](#query-locationcountry) as a plain `GET`, so a browser or an `hx-get`
can reach it without a request body — and so a caller building a name-to-id map
can page through it.

### Request

**Method:** `GET`
**Endpoint:** `/location/country`

### Query Parameters

| Name   | Type    | Required | Description                                |
|--------|---------|----------|--------------------------------------------|
| limit  | integer | No       | Max number of results, 1-100 (default 20)  |
| offset | integer | No       | Number of results to skip (default 0)      |

### Example Request

```bash
curl -X GET "http://localhost:9100/location/country?limit=100"
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

`total` counts every row, not just this page — page until you have `total` of
them.

### Error Responses

| Status | Description                        |
|--------|------------------------------------|
| 400    | `limit` or `offset` out of range   |
| 502    | Bad response from database service |
| 503    | Database service unavailable       |


## QUERY /location/country

Search countries. Uses the [HTTP QUERY method](https://datatracker.ietf.org/doc/draft-ietf-httpbis-safe-method-w-body/):
safe and idempotent like `GET`, but the filters travel in a request body instead
of the query string.

The body is forwarded to the database service as-is; see
[its QUERY](./database-service-api.md#query-internallocationcountry) for the
match template in full. `name` matches as a case-insensitive substring — this is
the endpoint a typeahead calls.

### Request

**Method:** `QUERY`
**Endpoint:** `/location/country`
**Content-Type:** `application/json`

### Example Request

```bash
curl -X QUERY "http://localhost:9100/location/country" \
  -H "Content-Type: application/json" \
  -d '{"country": {"name": "austral"}}'
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

| Status | Description                        |
|--------|------------------------------------|
| 400    | Unknown field                      |
| 502    | Bad response from database service |
| 503    | Database service unavailable       |

## City Endpoints

## GET /location/city/{id}

Retrieve a single city.

### Request

**Method:** `GET`
**Endpoint:** `/location/city/{id}`

### Path Parameters

| Name | Type | Required | Description            |
|------|------|----------|------------------------|
| id   | uuid | Yes      | Identifier of the city |

### Example Request

```bash
curl -X GET "http://localhost:9100/location/city/96318064-7cdc-54a8-a8d8-bb2c67d12c3e"
```

### Example Response `200 OK`

```json
{
  "id": "96318064-7cdc-54a8-a8d8-bb2c67d12c3e",
  "name": "sydney",
  "country_id": "36c95358-ac43-537d-ab58-8f4123ae55c0"
}
```

A city carries its `country_id`, not its country's name. A caller that needs
both already holds the country list.

### Error Responses

| Status | Description                        |
|--------|------------------------------------|
| 404    | City not found                     |
| 502    | Bad response from database service |
| 503    | Database service unavailable       |


## GET /location/city

Every city, paginated. Same shape and same purpose as
[GET /location/country](#get-locationcountry).

### Request

**Method:** `GET`
**Endpoint:** `/location/city`

### Query Parameters

| Name   | Type    | Required | Description                                |
|--------|---------|----------|--------------------------------------------|
| limit  | integer | No       | Max number of results, 1-100 (default 20)  |
| offset | integer | No       | Number of results to skip (default 0)      |

### Example Request

```bash
curl -X GET "http://localhost:9100/location/city?limit=100&offset=100"
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

| Status | Description                        |
|--------|------------------------------------|
| 400    | `limit` or `offset` out of range   |
| 502    | Bad response from database service |
| 503    | Database service unavailable       |


## QUERY /location/city

Search cities. Same method and same shape as the country query, plus an exact
match on `country_id`.

### Request

**Method:** `QUERY`
**Endpoint:** `/location/city`
**Content-Type:** `application/json`

### Example Request

```bash
curl -X QUERY "http://localhost:9100/location/city" \
  -H "Content-Type: application/json" \
  -d '{
    "city": {"name": "syd", "country_id": "36c95358-ac43-537d-ab58-8f4123ae55c0"}
  }'
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

| Status | Description                        |
|--------|------------------------------------|
| 400    | Unknown field                      |
| 502    | Bad response from database service |
| 503    | Database service unavailable       |

## Currency Endpoints

## GET /currency/country

The currency a country spends, by the country's name.

This is the endpoint most callers want. Everything else about a currency starts
from a `country_id`; this one starts from the country a caller actually has
written down, and does the two look-ups itself.

### Request

**Method:** `GET`
**Endpoint:** `/currency/country`

### Query Parameters

| Name | Type   | Required | Description                                                 |
|------|--------|----------|-------------------------------------------------------------|
| name | string | Yes      | Country name, matched **exactly** (case and padding ignored) |

`name` is an exact match here, unlike the substring matching in
[QUERY /location/country](#query-locationcountry). A search wants `"austral"` to
find Australia; a look-up that returns *a* currency for a half-typed country is
worse than one that returns nothing.

To go the other way — from a currency code to the countries that spend it — use
[QUERY /currency](#query-currency). A code is not unique, so that question has a
list for an answer and does not belong here.

### Example Request

```bash
curl -X GET "http://localhost:9100/currency/country?name=australia"
curl -X GET "http://localhost:9100/currency/country?name=new%20zealand"
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

One country has at most one currency, so this is a single currency and not a
list.

### Error Responses

| Status | Description                                            |
|--------|--------------------------------------------------------|
| 400    | `name` missing or empty                                 |
| 404    | `country not found` — no country by that name           |
| 404    | `country has no currency` — the country exists, but nothing records what it spends |
| 502    | Bad response from database service                      |
| 503    | Database service unavailable                            |

The two `404`s are deliberately different: one is the caller's typo, the other
is missing reference data. Read the `detail`.


## GET /currency/{id}

Retrieve a single currency.

### Request

**Method:** `GET`
**Endpoint:** `/currency/{id}`

### Path Parameters

| Name | Type | Required | Description                |
|------|------|----------|----------------------------|
| id   | uuid | Yes      | Identifier of the currency |

### Example Request

```bash
curl -X GET "http://localhost:9100/currency/41348563-8656-579b-917b-088fba86759a"
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

| Status | Description                        |
|--------|------------------------------------|
| 404    | Currency not found                 |
| 502    | Bad response from database service |
| 503    | Database service unavailable       |


## GET /currency

Every currency, paginated. There is one per country, so the whole list fits in a
page or two and a caller can hold it beside the country list it already keeps.

### Request

**Method:** `GET`
**Endpoint:** `/currency`

### Query Parameters

| Name   | Type    | Required | Description                                |
|--------|---------|----------|--------------------------------------------|
| limit  | integer | No       | Max number of results, 1-100 (default 20)  |
| offset | integer | No       | Number of results to skip (default 0)      |

### Example Request

```bash
curl -X GET "http://localhost:9100/currency?limit=100"
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

| Status | Description                        |
|--------|------------------------------------|
| 400    | `limit` or `offset` out of range   |
| 502    | Bad response from database service |
| 503    | Database service unavailable       |


## QUERY /currency

Search currencies. The body is forwarded to the database service as-is; see
[its QUERY](./database-service-api.md#query-internalcurrency) for the match
template in full. `country_id` is the usual filter — "what does this country
spend" — `code` matches exactly and case-insensitively, and `name` as a
case-insensitive substring.

Filtering on `code` can return several rows: `EUR` matches every country that
spends euros. `conversion_rate` is not filterable — exact equality on a float
matches nothing anyone meant.

### Request

**Method:** `QUERY`
**Endpoint:** `/currency`
**Content-Type:** `application/json`

### Example Request

```bash
curl -X QUERY "http://localhost:9100/currency" \
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

| Status | Description                        |
|--------|------------------------------------|
| 400    | Unknown field                      |
| 502    | Bad response from database service |
| 503    | Database service unavailable       |
