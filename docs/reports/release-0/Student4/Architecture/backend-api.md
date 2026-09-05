# Student 4 Backend/API Architecture

The backend is Student 4's public Activities and Attractions API. It keeps
public contracts independent from internal database schemas, translates
country and city names through the shared reference service, proxies itinerary
activity selections to Student 1, and uses AI Mode only for advisory search
planning and grounded recommendation evaluation.

```mermaid
flowchart LR
    FRONTEND[Student 4 frontend<br/>port 8084]
    CONSUMERS[Student 1 itinerary backend<br/>Student 5 budget backend]
    DATABASE[Student 4 database service<br/>port 8009<br/>/internal/activity]
    LOCATION[Shared backend<br/>port 9100<br/>/location]
    ITINERARY[Student 1 backend<br/>port 8001<br/>/api/trips and /api/activities]
    AI[Shared AI Mode<br/>port 8006<br/>POST /generate]

    subgraph BACKEND[Student 4 backend container - Compose-internal port 8008]
        APP[FastAPI composition root<br/>exception handling and dependency injection]
        ACTIVITY[Activity routes<br/>CRUD, categories and QUERY search]
        TRIPS[Itinerary routes<br/>selection and committed activity costs]
        RECOMMEND[Recommendation routes<br/>plan and evaluate]
        DBCLIENT[DatabaseClient<br/>internal contract validation]
        LOCATIONS[LocationClient<br/>name and UUID translation cache]
        TRIPCLIENT[ItineraryClient<br/>trip and activity selection proxy]
        AICLIENT[AI recommendation pipeline<br/>prompt filters and AiModeClient]
        STATUS[GET /health and GET /ready]

        APP --> ACTIVITY
        APP --> TRIPS
        APP --> RECOMMEND
        ACTIVITY --> DBCLIENT
        ACTIVITY --> LOCATIONS
        TRIPS --> DBCLIENT
        TRIPS --> TRIPCLIENT
        RECOMMEND --> DBCLIENT
        RECOMMEND --> LOCATIONS
        RECOMMEND --> TRIPCLIENT
        RECOMMEND --> AICLIENT
        STATUS --> DBCLIENT
        STATUS --> LOCATIONS
    end

    FRONTEND -->|HTTP JSON on /activity| APP
    CONSUMERS -->|Activity and cost HTTP APIs| APP
    DBCLIENT -->|HTTP internal API| DATABASE
    LOCATIONS -->|HTTP reference lookups| LOCATION
    TRIPCLIENT -->|HTTP itinerary reads and writes| ITINERARY
    AICLIENT -->|Structured advisory generation| AI
```

Database availability gates backend readiness. The broader health check also
reports location-service status. Itinerary and AI dependencies are deliberately
not readiness gates: ordinary catalogue operations can continue when those
optional capabilities are unavailable. AI output is validated and grounded
against database results and cannot write catalogue or itinerary state.

## Implementation sources

- [`app.py`](../../../../../student-4/backend/student4_backend_service/app.py)
- [`activity_routes.py`](../../../../../student-4/backend/student4_backend_service/activity_routes.py)
- [`itinerary_routes.py`](../../../../../student-4/backend/student4_backend_service/itinerary_routes.py)
- [`recommendation_routes.py`](../../../../../student-4/backend/student4_backend_service/recommendation_routes.py)
- [`docker-compose.yml`](../../../../../docker-compose.yml)
