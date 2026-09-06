# Student 4 Whole-Feature Architecture

The Activities and Attractions feature is delivered by three Student 4
microservices. The host-published frontend is the user entry point, the backend
owns the public feature API and all cross-service orchestration, and the
internal database service is the sole owner of the activity catalogue's SQLite
data. The dotted AI connection is advisory and cannot persist a change.

```mermaid
flowchart LR
    USER[Traveller or catalogue manager]
    S1[Student 1 itinerary backend<br/>port 8001]
    S5[Student 5 budget backend<br/>port 8005]
    LOC[Shared location backend<br/>port 9100]
    AI[Shared AI Mode<br/>port 8006]

    subgraph FEATURE[Student 4 - Activities and Attractions Management]
        direction LR

        subgraph FRONTEND[Frontend container - host port 8084]
            UI[FastAPI, Jinja2 and HTMX<br/>catalogue and management UI]
            FECLIENT[Typed BackendClient<br/>HTTP and Pydantic validation]
            UI --> FECLIENT
        end

        subgraph BACKEND[Backend API container - internal port 8008]
            API[FastAPI public API<br/>/activity routes]
            CATALOGUE[Catalogue orchestration<br/>CRUD, search and locations]
            TRIPS[Itinerary and committed-cost bridge]
            RECOMMEND[Grounded AI recommendation pipeline]
            STATUS[Health and readiness checks]
            DBCLIENT[Typed DatabaseClient<br/>internal contract validation]

            API --> CATALOGUE
            API --> TRIPS
            API --> RECOMMEND
            API --> STATUS
            CATALOGUE --> DBCLIENT
            TRIPS --> DBCLIENT
            RECOMMEND --> DBCLIENT
            STATUS --> DBCLIENT
        end

        subgraph DATABASE[Database container - internal port 8009]
            INTERNAL[FastAPI internal API<br/>/internal/activity]
            REPOSITORY[ActivityRepository<br/>transactions and filtering]
            STORE[(SQLite activities.db<br/>student-4-sqlite volume)]

            INTERNAL --> REPOSITORY
            REPOSITORY --> STORE
        end

        FECLIENT -->|HTTP JSON| API
        DBCLIENT -->|HTTP internal contract| INTERNAL
    end

    USER -->|Pages, forms and HTMX requests| UI
    S1 -->|Activity catalogue lookups| API
    S5 -->|Committed activity cost items and total| API
    CATALOGUE -->|Country and city reference lookups| LOC
    RECOMMEND -->|Location vocabulary and trip destination| LOC
    STATUS -->|Location health check| LOC
    TRIPS -->|Trip activity reads and writes| S1
    RECOMMEND -->|Trip context and selected activities| S1
    RECOMMEND -.->|Advisory POST /generate| AI
```

No caller accesses the Student 4 database service or SQLite file directly.
Public location names are translated by the backend to shared-service UUIDs
before database requests. Trip selections remain owned by Student 1, while
Student 5 consumes Student 4's calculated committed activity cost items and
total through the public backend API.

## Detailed diagrams

- [Frontend architecture](frontend.md)
- [Backend/API architecture](backend-api.md)
- [Database architecture](database.md)
