# Student 4 Whole-Feature Architecture

This high-level diagram shows how the Student 4 Activities and Attractions
services interact with each other and with the other TripGenie services they
depend on. Detailed components inside each Student 4 service are documented in
the separate diagrams linked below.

Each bordered card represents an independently deployed service. A
high-resolution [PNG export](overview.png) is included alongside this document
for use in reports and presentations.

```mermaid
%%{init: {"theme":"base","themeVariables":{"fontFamily":"Inter, ui-sans-serif, system-ui, sans-serif","primaryTextColor":"#0f172a","lineColor":"#64748b","clusterBkg":"#f8fafc","clusterBorder":"#cbd5e1"},"flowchart":{"curve":"basis","nodeSpacing":46,"rankSpacing":64}}}%%
flowchart TB
    USER[Traveller or catalogue manager]

    subgraph FEATURE[Activities & Attractions Management]
        direction LR
        FRONTEND[student-4-frontend<br/><b>Frontend service</b><br/>host :8084]
        BACKEND[student-4-backend<br/><b>Backend API service</b><br/>internal :8008]
        DATABASE[student-4-database<br/><b>Database API service</b><br/>internal :8009]
        STORE[(Activities & attractions<br/>SQLite database)]

        FRONTEND -->|public HTTP API| BACKEND
        BACKEND -->|internal HTTP API only| DATABASE
        DATABASE -->|sole SQLite access| STORE
    end

    subgraph RELATED[Related TripGenie services]
        direction LR
        LOCATION[shared-backend<br/><b>Reference-data API service</b><br/>:9100]
        ITINERARY[student-1-backend<br/><b>Trip & itinerary API service</b><br/>:8001]
        BUDGET[student-5-backend<br/><b>Budget & expense API service</b><br/>:8005]
        AI[ai-mode<br/><b>Shared AI gateway service</b><br/>:8006]
        OLLAMA[Host-managed Ollama<br/><b>External runtime</b><br/>:11434]
    end

    USER -->|Pages, forms and HTMX requests| FRONTEND
    BACKEND -->|Country and city lookups| LOCATION
    BACKEND <-->|Trip assignments & activity catalogue| ITINERARY
    BUDGET -->|Committed activity cost requests| BACKEND
    BACKEND -.->|Advisory AI generation| AI
    AI -->|Only Ollama client| OLLAMA

    classDef actor fill:#f8fafc,stroke:#64748b,color:#0f172a,stroke-width:2px;
    classDef frontend fill:#dbeafe,stroke:#2563eb,color:#0f172a,stroke-width:2px;
    classDef backend fill:#dcfce7,stroke:#16a34a,color:#0f172a,stroke-width:2px;
    classDef dbapi fill:#ffedd5,stroke:#ea580c,color:#0f172a,stroke-width:3px;
    classDef database fill:#fef3c7,stroke:#d97706,color:#0f172a,stroke-width:2px;
    classDef related fill:#f3e8ff,stroke:#9333ea,color:#0f172a,stroke-width:2px;
    classDef external fill:#f1f5f9,stroke:#64748b,color:#0f172a,stroke-width:2px,stroke-dasharray:5 5;
    class USER actor;
    class FRONTEND frontend;
    class BACKEND backend;
    class DATABASE dbapi;
    class STORE database;
    class LOCATION,ITINERARY,BUDGET,AI related;
    class OLLAMA external;
    style FEATURE fill:#ffffff,stroke:#60a5fa,stroke-width:2px;
    style RELATED fill:#faf5ff,stroke:#a855f7,stroke-width:2px;
```

Only the frontend is published to the host. All database access and
cross-service calls pass through the Student 4 backend. The AI connection is
advisory and cannot persist catalogue or itinerary changes directly. The
database API service is the only process that opens the Student 4 SQLite file.

## Detailed diagrams

- [Frontend architecture](frontend.md)
- [Backend/API architecture](backend-api.md)
- [Database architecture](database.md)
