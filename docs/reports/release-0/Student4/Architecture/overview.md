# Student 4 Whole-Feature Architecture

This high-level diagram shows how the Student 4 Activities and Attractions
services interact with each other and with the other TripGenie services they
depend on. Detailed components inside each Student 4 service are documented in
the separate diagrams linked below.

```mermaid
flowchart LR
    USER[Traveller or catalogue manager]

    subgraph FEATURE[Student 4 - Activities and Attractions Management]
        direction LR
        FRONTEND[Frontend service<br/>host port 8084]
        BACKEND[Backend API service<br/>internal port 8008]
        DATABASE[Database service<br/>internal port 8009]
        STORE[(Activities SQLite database)]

        FRONTEND -->|Public activity API| BACKEND
        BACKEND -->|Internal activity API| DATABASE
        DATABASE -->|Reads and writes| STORE
    end

    LOCATION[Shared location service<br/>port 9100]
    ITINERARY[Student 1 itinerary service<br/>port 8001]
    BUDGET[Student 5 budget service<br/>port 8005]
    AI[Shared AI Mode service<br/>port 8006]

    USER -->|Pages, forms and HTMX requests| FRONTEND
    BACKEND -->|Country and city lookups| LOCATION
    BACKEND -->|Trip reads and writes| ITINERARY
    ITINERARY -->|Activity catalogue lookups| BACKEND
    BUDGET -->|Committed activity cost requests| BACKEND
    BACKEND -.->|Advisory AI generation| AI
```

Only the frontend is published to the host. All database access and
cross-service calls pass through the Student 4 backend. The AI connection is
advisory and cannot persist catalogue or itinerary changes directly.

## Detailed diagrams

- [Frontend architecture](frontend.md)
- [Backend/API architecture](backend-api.md)
- [Database architecture](database.md)
