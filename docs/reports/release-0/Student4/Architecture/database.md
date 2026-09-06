# Student 4 Database Architecture

The database microservice is an internal FastAPI application and the sole owner
of Student 4's activity data. Thin HTTP routers validate internal wire schemas
and delegate transactional catalogue CRUD and search to a SQLAlchemy repository,
which persists the activity aggregate in a dedicated SQLite file.

```mermaid
flowchart LR
    BACKEND[Student 4 backend API<br/>sole service caller<br/>port 8008]

    subgraph DATABASE[Student 4 database container - Compose-internal port 8009]
        APP[FastAPI composition root<br/>lifespan and error handlers]
        ROUTES[Internal activity router<br/>CRUD, categories and QUERY search<br/>/internal/activity]
        HEALTH[Database health route<br/>GET /internal/health]
        SCHEMAS[Pydantic internal schemas<br/>aggregate and query validation]
        REPOSITORY[ActivityRepository<br/>transactions, filters and eager loading]
        ORM[SQLAlchemy models and session factory<br/>constraints, indexes and cascades]
        SEED[Idempotent seed data<br/>enabled by SEED_DATA]
        SQLITE[(SQLite activities.db<br/>named volume student-4-sqlite)]

        APP --> ROUTES
        APP --> HEALTH
        APP --> SEED
        ROUTES --> SCHEMAS
        ROUTES --> REPOSITORY
        REPOSITORY --> ORM
        HEALTH --> ORM
        SEED --> ORM
        ORM --> SQLITE
    end

    BACKEND -->|HTTP JSON internal contract| APP
```

The service makes no outbound service calls. Shared country and city UUIDs are
stored as external references, not joined across databases. On startup or the
first request, the service creates the schema and optionally seeds reference and
catalogue rows. SQLite foreign-key enforcement is enabled for every connection.

## Implementation sources

- [`app.py`](../../../../../student-4/database/student4_database_service/app.py)
- [`repository.py`](../../../../../student-4/database/student4_database_service/repository.py)
- [`models.py`](../../../../../student-4/database/student4_database_service/models.py)
- [`database.py`](../../../../../student-4/database/student4_database_service/database.py)
- [`docker-compose.yml`](../../../../../docker-compose.yml)
