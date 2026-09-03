← Back to [README.md](../README.md)

# Accommodation Micro-Service

The accommodation microservice is responsible for all accommodation related business functions. A few are listed below:

1. Users can view accommodation details
2. Users can filter for accommodation based on properties such as price, type, location, etc.

As such, the service has providence over the objects expanded on in [object-model.md](./docs/object-model.md).

The micro-service is comprised of three services:

1. The backend service
2. The database service
3. The frontend service

## Running It

From the repo root:

```bash
docker compose up --build student-2
```

`student-2` is a grouping entry, not a service — it exits immediately, and the
three services it depends on are the point. They keep running in the
background, so you get your prompt back. The page is at
<http://localhost:9003> and the backend API at <http://localhost:9000>; the
database service stays on the compose network, unpublished.

Either end of the chain works if you want less than all three:

| Command | Starts |
| --- | --- |
| `docker compose up --build student-2` | all three |
| `docker compose exec ollama ollama pull llama3.1:8b` | the model the ask box needs, once |
| `docker compose up --build student-2-backend` | backend + database |
| `docker compose up --build student-2-database` | database only |
| `docker compose logs -f student-2-frontend` | follow one service's logs |
| `docker compose down` | stop them |

`--build` matters: without it compose reuses the image it built last time and
your code changes never make it into the container. The seeded rows live in the
`student-2-db` volume and survive a rebuild — `docker compose down -v` to wipe
them and re-seed.

There is also `student-2/Dockerfile`, which runs all three services in a single
container. Compose does not use it; it is there for `docker build -t student-2
student-2 && docker run --rm -p 9003:9003 -p 9000:9000 student-2`.

## Backend Service

This service is the main entry point for queries coming in from the frontend. 
This is responsible for managing data models in the accommodation database via the database service.
It is also where this micro-service is integrated with Artificial Intelligence,
in order to answer a question in English with real accommodations:
[`POST /accommodation/ai-search`](./docs/backend-service-api.md#post-accommodationai-search).
The model produces *filters*, never listings -- they are validated as the
service's own search message and then run through the ordinary search -- and the
model itself lives in neither this service nor this micro-service, but behind the
[shared AI-Mode service](../ai-services/ai-mode/README.md) that every student's
backend calls.

It is also where this micro-service reaches the two services outside it: student
1's itinerary API, and the [shared reference service](../shared/shared-service.md)
that owns `Country` and `City`. The accommodation database stores a country id
and a city id; this service turns those into names on the way out and names into
ids on the way in, so callers of the accommodation API never see an id and there
is only one list of places in the system.

It runs as the `student-2-backend` container on port `9000`, published to the
host, and is the only service permitted to call the database service.

**API Documentation**: [backend-service-api.md](./docs/backend-service-api.md)

## Database Service

This service is essentially a wrapper for all database queries so that other services such as the backend service can manage data within the accommodation database with ease through HTTP requests on the wire.
This service is an internal service that is only exposed to the backend service for querying.

Built with FastAPI over the SQLAlchemy models in `database/database_service/`.
It runs as the `student-2-database` container on port `9001`, `expose`d on the
compose network but not published to the host. Start it with
`docker compose up student-2-database`.

**API Documentation**: [database-service-api.md](./docs/database-service-api.md)

## Frontend Service

The webpage: an ask box, a list of accommodations with live search, a filter for
every property that can be filtered on, a details modal per row, and a pager
with a configurable page size. Asking a question fills the filter form in, so
the AI is a shortcut to the controls that were already there rather than a
second, separate way to search. It calls the backend service and nothing else.

It runs as the `student-2-frontend` container on port `9003`, published to the
host, and is what `shared/frontend/index.html` links to for Student 2.

```bash
docker compose up student-2-frontend
```

The page is HTMX over server-rendered Jinja fragments. HTMX swaps *HTML*, and
the backend serves JSON, so this service is what turns one into the other — and
the only filtered search the backend offers is `QUERY /accommodation` with a
JSON body, a method HTMX cannot issue. The filter form arrives here as query
parameters and leaves as that body.

**Service documentation**: [frontend-service.md](./docs/frontend-service.md)