# Student 4 Conceptual Data Design

`Activity` is the single catalogue concept for both activities and attractions.
For example, museum admission and a guided tour of that museum are separate
activities when their price, duration or availability differs. Location and
schedule data belong to that catalogue entry, while seeded categories provide
a controlled way to classify and filter it.

This view deliberately omits attributes, keys, storage types and table names.
It describes the business concepts only. A high-resolution
[PNG export](conceptual.png) is included alongside this document.

```mermaid
%%{init: {"theme":"base","themeVariables":{"fontFamily":"Inter, ui-sans-serif, system-ui, sans-serif","primaryTextColor":"#0f172a","lineColor":"#64748b","clusterBkg":"#f8fafc","clusterBorder":"#cbd5e1"},"flowchart":{"curve":"basis","nodeSpacing":58,"rankSpacing":72}}}%%
flowchart LR
    subgraph OWNED[Activities & Attractions domain]
        direction LR
        ACTIVITY[<b>Activity</b><br/>catalogue offering]
        LOCATION[<b>Location details</b><br/>owned place information]
        CATEGORY[<b>Category</b><br/>controlled classification]
        SCHEDULE[<b>Availability schedule</b><br/>weekly or one-off]
    end

    subgraph EXTERNAL[Shared reference domain]
        PLACE[<b>Country & city</b><br/>authoritative shared concepts]
    end

    ACTIVITY -->|takes place at exactly one| LOCATION
    ACTIVITY <-->|classified by one or more| CATEGORY
    ACTIVITY -->|"inactive: zero or more; active: one or more"| SCHEDULE
    LOCATION -.->|references by UUID| PLACE

    classDef core fill:#dcfce7,stroke:#16a34a,color:#0f172a,stroke-width:3px;
    classDef owned fill:#dbeafe,stroke:#2563eb,color:#0f172a,stroke-width:2px;
    classDef external fill:#f3e8ff,stroke:#9333ea,color:#0f172a,stroke-width:2px,stroke-dasharray:5 5;
    class ACTIVITY core;
    class LOCATION,CATEGORY,SCHEDULE owned;
    class PLACE external;
    style OWNED fill:#ffffff,stroke:#60a5fa,stroke-width:2px;
    style EXTERNAL fill:#faf5ff,stroke:#a855f7,stroke-width:2px;
```

An inactive catalogue entry may have no schedule, but an active activity must
have at least one. Country and city remain authoritative in the shared
reference service, so the dotted connection is a UUID reference across service
boundaries rather than a relationship between tables in one database.
