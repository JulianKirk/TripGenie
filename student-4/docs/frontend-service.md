← Back to [README.md](../../README.md)

# Activities and Attractions Frontend Service

## Service scope

This service renders Student 4's traveller catalogue and management interface. It
talks only to the [Student 4 backend](./backend-service-api.md), never to the
database or shared reference services.

```text
              browser
                 |  :8084 host / container  HTML
                 v
       student-4-frontend -- Jinja templates + HTMX
                 |  :8008  activity and itinerary-proxy routes
                 v
        student-4-backend
```

The backend returns JSON, while HTMX swaps HTML fragments. The frontend service
therefore owns presentation and translates browser-friendly `GET` parameters
into the backend's structured `QUERY /activity` body. It does not duplicate
database filtering logic.

The page covers both activities and attractions because both are represented
by the single `Activity` model. It intentionally contains no image UI and no
booking or payment workflow.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `BACKEND_URL` | `http://student-4-backend:8008` | Student 4 backend-service base URL. |
| `BACKEND_TIMEOUT` | `5` | Backend request timeout in seconds. |
| `AI_TIMEOUT` | `210` | Timeout for each AI planning or evaluation request only. |

Run the frontend with:

```bash
docker compose up student-4-frontend
```

Then open `http://localhost:8084`. Start the complete Student 4 slice with
`docker compose up --build --remove-orphans student-4`. The orphan cleanup
removes the retired `student-4-service` directory-server container if it exists,
freeing the assignment port for the real frontend.

## HTML routes

These routes return pages or fragments, not a public JSON API.

| Route | Returns |
|---|---|
| `GET /` | Unified catalogue and CRUD page, including inactive entries. |
| `GET /activity` | Results-and-pagination HTML fragment. |
| `GET /activity/{id}` | Full activity-detail dialog fragment. |
| `GET /activity/{id}/itineraries/dialog` | Direct trip-picker dialog fragment. |
| `GET /activity/{id}/itineraries` | Itinerary picker fragment from the Student 4 proxy. |
| `PUT /activity/{id}/itineraries/{trip_id}` | Add or reschedule an itinerary selection. |
| `DELETE /activity/{id}/itineraries/{trip_id}` | Remove an itinerary selection. |
| `GET /manage` | Legacy catalogue management page. |
| `GET /manage/activity/new` | Create-activity form fragment. |
| `POST /manage/activity` | Create a complete activity aggregate. |
| `GET /manage/activity/{id}/edit` | Prefilled edit form fragment. |
| `PUT /manage/activity/{id}` | Replace a complete activity aggregate. |
| `GET /manage/activity/{id}/delete` | Permanent-delete confirmation fragment. |
| `DELETE /manage/activity/{id}` | Permanently delete an activity aggregate. |
| `GET /health` | Frontend and backend health JSON. |
| `GET /ready` | Readiness JSON; returns `503` until the backend is ready. |
| `POST /suggestions/ask` | Submit a question and optional trip to the shared MCP assistant. |

`GET /health` returns `200` with `status: "degraded"` when the backend cannot be
reached, matching the other frontend services.

`GET /ready` returns `503` until the public backend reports that its required
database dependency is ready. Docker Compose uses this endpoint to gate the
Student 4 grouping target.

## Page structure

The traveller page has four regions:

1. A heading explaining that attractions and activities share one catalogue.
2. One search-and-filter form.
3. An `aria-live` results region containing create and per-card edit controls,
   cards, count and pager.
4. A dialog target populated when a user opens an activity.

The catalogue includes inactive entries and provides creation, replacement,
deactivation and deletion without requiring a separate management page.

## MCP activity assistant

The primary AI panel submits a question and optional trip through
`POST /suggestions/ask` to backend `/activity/assistant`. Each request is independent.
Shared AI-Mode performs model-directed MCP calls; the frontend renders escaped
model text and authoritative activity cards resolved by its own backend.

**Tools used** shows names, arguments, status, timings, errors and expandable actual
returned MCP data, including other domains. Failed runs retain completed calls.
The assistant can execute requested actions through advertised write tools; the UI
therefore does not promise that nothing has been saved. Ordinary activity and
itinerary actions remain available. Loading state and full-page form fallback are
preserved. See [setup](mcp-assistant.md).
