# Student 1 backend service

This FastAPI service exposes the public TripGenie Student 1 `/api` CRUD surface and talks to the Student 1 database service over HTTP only.

## Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `STUDENT1_BACKEND_API_PREFIX` | `/api` | Public API prefix. |
| `STUDENT1_BACKEND_DB_API_BASE_URL` | `http://student-1-database:8002` | Base URL for the internal Student 1 database API. |
| `STUDENT1_BACKEND_DB_API_PREFIX` | `/internal` | Internal Student 1 database API prefix. |
| `STUDENT1_BACKEND_DB_API_TIMEOUT_SECONDS` | `5` | Timeout for backend-to-database HTTP calls. |
| `STUDENT1_BACKEND_OLLAMA_BASE_URL` | _unset_ | Optional Ollama URL reported by health status only in issue #10. |
| `STUDENT1_BACKEND_SERVICE_NAME` | `student-1-backend` | Service name reported by health endpoints. |

## Trip duration rule

TripGenie applies a project-specific maximum trip duration of **366 inclusive calendar days**. `POST /api/trips` and effective `PATCH /api/trips/{tripId}` payloads that exceed that limit return the normal validation envelope, and trip detail responses refuse oversized upstream records with a dependency error instead of expanding an unbounded `days` list.

## Current concurrency note

`PATCH` flows use a read-merge-write pattern against the database API so the backend can validate effective records before forwarding partial updates. The current internal API does not expose record versions or conditional writes, so concurrent updates are still last-write-wins across services; the backend re-reads committed state after writes and the database API remains the final validation guard.
