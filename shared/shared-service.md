← Back to [README.md](../README.md)

# Shared Reference Micro-Service

The shared reference microservice owns the data that is nobody's feature and
everybody's dependency. Today that is places and the money spent in them:

1. Every service needs to say where something is
2. Every service that shows a price needs to say what the price is in
3. No service should keep its own private list of countries, cities or currencies

`Country` and `City` used to live in the accommodation service's `models.py`,
under a heading that admitted the arrangement was temporary. They live here now,
alongside `Currency` — one per country — and the entities are expanded on in
[object-model.md](./docs/object-model.md).

The micro-service is comprised of two services:

1. The backend service
2. The database service

There is no frontend service. Nobody browses a list of countries as a feature —
the other students' pages are what put these names on a screen. (`shared/frontend/`
is the portal page that links to each student's service; it is a different thing
and predates this micro-service.)

## Running It

From the repo root:

```bash
docker compose up --build shared-backend
```

The backend depends on the database service, so that one command starts both.
The API is at <http://localhost:9100>; the database service stays on the compose
network, unpublished.

| Command | Starts |
| --- | --- |
| `docker compose up --build shared-backend` | both |
| `docker compose up --build shared-database` | database only |
| `docker compose logs -f shared-backend` | follow one service's logs |
| `docker compose down` | stop them |

`--build` matters: without it compose reuses the image it built last time and
your code changes never make it into the container. The seeded rows live in the
`shared-db` volume and survive a rebuild — `docker compose down -v` to wipe them
and re-seed.

## Who Uses It

Student 2's backend service, so far. An accommodation row stores a country id
and a city id; the accommodation backend calls this service to turn a place name
into an id on the way in and back into a name on the way out, so its own public
contract still speaks names. See
[student-2/docs/backend-service-api.md](../student-2/docs/backend-service-api.md).

Any service that stores a place should do the same. The rule for everyone is the
same one student 2 follows: **store the id, publish the name, and let this
service be the only thing that knows both.**

Currencies are there for whoever needs them next — student 5's budget service is
the obvious one, and student 2's prices are in AUD today because nothing yet
says otherwise. Asking takes one request:

```bash
curl "http://localhost:9100/currency/country?name=japan"
# -> {"name": "japanese yen", "code": "JPY", "symbol": "¥", "conversion_rate": 98.0, ...}
```

A country name in, and back comes its currency: the ISO 4217 code, the symbol a
page renders, and `conversion_rate` — how many units of it 1 AUD buys. Prices
here are quoted in AUD, so AUD is the base and its own row is `1.0`, which makes
converting a multiplication rather than a branch. The rates are static and
indicative; nothing refreshes them yet.

Going the other way — "who spends EUR" — is a `QUERY /currency` on the code,
because a code names a currency rather than a row and France and Italy both
answer to it.

## Backend Service

The public entry point. Read-only: it serves the reference lists and the
`GET /{id}` look-ups, and forwards searches to the database service. It does not
create places or currencies — the lists are seeded, and a service that invents
countries on demand is a service that quietly accumulates typos.

It runs as the `shared-backend` container on port `9100`, published to the host,
and is the only service permitted to call the database service.

**API Documentation**: [backend-service-api.md](./docs/backend-service-api.md)

## Database Service

A wrapper around the shared reference SQLite database so the backend service can
manage its data through HTTP requests on the wire. This service is internal and
is only exposed to the backend service for querying.

Built with FastAPI over the SQLAlchemy models in `database/shared_database_service/`.
It runs as the `shared-database` container on port `9101`, `expose`d on the
compose network but not published to the host. Start it with
`docker compose up shared-database`.

**API Documentation**: [database-service-api.md](./docs/database-service-api.md)
