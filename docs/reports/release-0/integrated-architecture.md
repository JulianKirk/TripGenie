# TripGenie Release 0 Integrated Architecture

This diagram reflects the services declared in the root
[`docker-compose.yml`](../../../docker-compose.yml). Each feature owns a
frontend, a public backend API, and an internal database API service. The
database API service is the **only** process allowed to open that feature's
SQLite database; neither the frontend nor the backend accesses SQLite
directly.

## Deployment and storage ownership

```mermaid
flowchart TB
    USER[Traveller / browser]
    PORTAL[Shared portal<br/>host :8080]

    USER -->|opens| PORTAL

    subgraph FEATURES[Feature services]
        direction LR

        subgraph TRIPS[Trip & Itinerary Management]
            direction TB
            T_FE[Frontend<br/>host :8081]
            T_BE[Backend API<br/>internal :8001]
            T_DB_API[Database API service<br/>internal :8002]
            T_DB[(Trip & itinerary<br/>SQLite database)]
            T_FE -->|HTTP API| T_BE
            T_BE -->|internal HTTP API only| T_DB_API
            T_DB_API -->|sole SQLite access| T_DB
        end

        subgraph ACCOMMODATION[Accommodation Management]
            direction TB
            A_FE[Frontend<br/>host :9003]
            A_BE[Backend API<br/>host :9000]
            A_DB_API[Database API service<br/>internal :9001]
            A_DB[(Accommodation<br/>SQLite database)]
            A_FE -->|HTTP API| A_BE
            A_BE -->|internal HTTP API only| A_DB_API
            A_DB_API -->|sole SQLite access| A_DB
        end

        subgraph TRANSPORT[Transport Management]
            direction TB
            R_FE[Frontend<br/>host :8093]
            R_BE[Backend API<br/>internal :8003]
            R_DB_API[Database API service<br/>internal :8004]
            R_DB[(Transport<br/>SQLite database)]
            R_FE -->|HTTP API| R_BE
            R_BE -->|internal HTTP API only| R_DB_API
            R_DB_API -->|sole SQLite access| R_DB
        end

        subgraph ACTIVITIES[Activities & Attractions Management]
            direction TB
            C_FE[Frontend<br/>host :8084]
            C_BE[Backend API<br/>internal :8008]
            C_DB_API[Database API service<br/>internal :8009]
            C_DB[(Activities & attractions<br/>SQLite database)]
            C_FE -->|HTTP API| C_BE
            C_BE -->|internal HTTP API only| C_DB_API
            C_DB_API -->|sole SQLite access| C_DB
        end

        subgraph BUDGET[Budget & Expense Management]
            direction TB
            B_FE[Frontend<br/>host :8085]
            B_BE[Backend API<br/>internal :8005]
            B_DB_API[Database API service<br/>internal :8007]
            B_DB[(Budget & expense<br/>SQLite database)]
            B_FE -->|HTTP API| B_BE
            B_BE -->|internal HTTP API only| B_DB_API
            B_DB_API -->|sole SQLite access| B_DB
        end
    end

    PORTAL -.->|links to| T_FE
    PORTAL -.->|links to| A_FE
    PORTAL -.->|links to| R_FE
    PORTAL -.->|links to| C_FE
    PORTAL -.->|links to| B_FE

    subgraph SHARED[Shared platform services]
        direction LR
        REF_BE[Reference-data backend API<br/>host :9100]
        REF_DB_API[Reference database API service<br/>internal :9101]
        REF_DB[(Country & city<br/>SQLite database)]
        AI[Shared AI Mode gateway<br/>internal :8006]
        OLLAMA[Host-managed Ollama<br/>host :11434]

        REF_BE -->|internal HTTP API only| REF_DB_API
        REF_DB_API -->|sole SQLite access| REF_DB
        AI -->|only Ollama client| OLLAMA
    end

    T_BE -.->|AI generation| AI
    A_BE -.->|AI generation| AI
    R_BE -.->|AI generation| AI
    C_BE -.->|AI generation| AI
    B_BE -.->|AI generation| AI

    classDef frontend fill:#dbeafe,stroke:#2563eb,color:#111827;
    classDef backend fill:#dcfce7,stroke:#16a34a,color:#111827;
    classDef dbapi fill:#ffedd5,stroke:#ea580c,color:#111827,stroke-width:2px;
    classDef database fill:#fef3c7,stroke:#d97706,color:#111827;
    classDef shared fill:#f3e8ff,stroke:#9333ea,color:#111827;
    class T_FE,A_FE,R_FE,C_FE,B_FE frontend;
    class T_BE,A_BE,R_BE,C_BE,B_BE backend;
    class T_DB_API,A_DB_API,R_DB_API,C_DB_API,B_DB_API,REF_DB_API dbapi;
    class T_DB,A_DB,R_DB,C_DB,B_DB,REF_DB database;
    class PORTAL,REF_BE,AI,OLLAMA shared;
```

Solid arrows represent runtime HTTP or storage calls. Dotted arrows represent
portal navigation or optional AI-generation calls. Database APIs stay internal
to their owning feature.

## Backend API integration

Cross-feature requests go only to public backend APIs. No feature can call
another feature's database API or open another feature's SQLite database.

```mermaid
flowchart LR
    TRIPS[Trip & Itinerary API<br/>:8001]
    ACCOMMODATION[Accommodation API<br/>:9000]
    TRANSPORT[Transport API<br/>:8003]
    ACTIVITIES[Activities & Attractions API<br/>:8008]
    BUDGET[Budget & Expense API<br/>:8005]
    REFERENCE[Reference-data API<br/>:9100]
    AI[Shared AI Mode API<br/>:8006]

    TRIPS -->|accommodation lookups| ACCOMMODATION
    TRIPS -->|transport lookups| TRANSPORT
    TRIPS -->|activity lookups| ACTIVITIES
    ACCOMMODATION -->|trip reads & assignments| TRIPS
    ACCOMMODATION -->|country & city lookups| REFERENCE
    TRANSPORT -->|trip lookups| TRIPS
    ACTIVITIES -->|trip reads & activity assignments| TRIPS
    ACTIVITIES -->|country & city lookups| REFERENCE
    BUDGET -->|trip costs| TRIPS
    BUDGET -->|accommodation costs| ACCOMMODATION
    BUDGET -->|transport costs| TRANSPORT
    BUDGET -->|activity costs| ACTIVITIES

    TRIPS -.->|generation requests| AI
    ACCOMMODATION -.->|generation requests| AI
    TRANSPORT -.->|generation requests| AI
    ACTIVITIES -.->|generation requests| AI
    BUDGET -.->|generation requests| AI

    classDef api fill:#dcfce7,stroke:#16a34a,color:#111827;
    classDef shared fill:#f3e8ff,stroke:#9333ea,color:#111827;
    class TRIPS,ACCOMMODATION,TRANSPORT,ACTIVITIES,BUDGET api;
    class REFERENCE,AI shared;
```

The `student-1` through `student-5` Compose services are lightweight grouping
targets, so they are not runtime application nodes in the diagram.
