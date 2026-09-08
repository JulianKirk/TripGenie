# Student 5 Conceptual Data Design

`Budget` captures the spending limit and planned category allocations for one
trip. `Expense` captures an individual amount actually spent for that trip.
Each trip may have at most one budget and any number of expenses, while the two
Student 5 concepts have independent lifecycles.

This view deliberately omits attributes, keys, storage types and table names.
It describes the business concepts and ownership boundaries only. A
high-resolution [PNG export](conceptual.png) is included alongside this
document.

```mermaid
%%{init: {"theme":"base","themeVariables":{"fontFamily":"Inter, ui-sans-serif, system-ui, sans-serif","primaryTextColor":"#0f172a","lineColor":"#64748b","clusterBkg":"#f8fafc","clusterBorder":"#cbd5e1"},"flowchart":{"curve":"basis","nodeSpacing":64,"rankSpacing":88}}}%%
flowchart LR
    subgraph EXTERNAL[Trips domain - Student 1]
        TRIP[<b>Trip</b><br/>authoritative travel plan]
    end

    subgraph OWNED[Budget & Expenses domain - Student 5]
        direction TB
        BUDGET[<b>Budget</b><br/>spending limit and allocations]
        EXPENSE[<b>Expense</b><br/>recorded actual spending]
    end

    TRIP -.->|"per Trip: zero or one Budget; each Budget: exactly one Trip"| BUDGET
    TRIP -.->|"per Trip: zero or more Expenses; each Expense: exactly one Trip"| EXPENSE

    classDef core fill:#dcfce7,stroke:#16a34a,color:#0f172a,stroke-width:3px;
    classDef owned fill:#dbeafe,stroke:#2563eb,color:#0f172a,stroke-width:2px;
    classDef external fill:#f3e8ff,stroke:#9333ea,color:#0f172a,stroke-width:2px,stroke-dasharray:5 5;
    class BUDGET core;
    class EXPENSE owned;
    class TRIP external;
    style OWNED fill:#ffffff,stroke:#60a5fa,stroke-width:2px;
    style EXTERNAL fill:#faf5ff,stroke:#a855f7,stroke-width:2px;
```

Trip remains authoritative in Student 1. The dotted connections cross a
service ownership boundary rather than representing database foreign keys.
Deleting a Student 5 budget has no effect on the Trip or its expenses.