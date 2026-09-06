# Student 4 Frontend Architecture

The frontend is a server-rendered FastAPI application. It uses Jinja2 templates
for full pages and HTMX fragments for interactive catalogue search, itinerary
selection, AI-assisted suggestions, and catalogue management. A typed `httpx`
client is its only service dependency and sends every data operation to the
Student 4 backend/API.

```mermaid
flowchart LR
    USER[Traveller or catalogue manager]
    THEME[Shared portal theme<br/>localhost:8080]
    HTMX[HTMX browser library<br/>CDN]
    BACKEND[Student 4 backend API<br/>Compose-internal port 8008]

    subgraph FRONTEND[Student 4 frontend container - host port 8084]
        APP[FastAPI routes<br/>catalogue, AI, itinerary, management]
        VIEW[Jinja2 templates and HTMX fragments]
        UI[Form parsing, query building,<br/>presenters and static assets]
        CLIENT[Typed BackendClient<br/>httpx and Pydantic validation]
        HEALTH[Health and readiness routes<br/>GET /health and GET /ready]

        APP --> VIEW
        APP --> UI
        APP --> CLIENT
        HEALTH --> CLIENT
    end

    USER -->|HTTP pages, forms and HTMX requests| APP
    VIEW -->|HTML responses| USER
    USER -.->|CSS| THEME
    USER -.->|JavaScript| HTMX
    CLIENT -->|HTTP JSON operations| BACKEND
```

The frontend never calls the database, location, itinerary, or AI services
directly. Its `/ready` endpoint succeeds only when the backend reports ready;
its `/health` endpoint reports a degraded state when the backend is unavailable.

## Implementation sources

- [`app.py`](../../../../../student-4/frontend/student4_frontend_service/app.py)
- [`client.py`](../../../../../student-4/frontend/student4_frontend_service/client.py)
- [`docker-compose.yml`](../../../../../docker-compose.yml)
