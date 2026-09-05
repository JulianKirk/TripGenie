# Student 4 Entity-Relationship Diagram

Each activity owns exactly one `LOCATION_DETAILS` row and at least one category
assignment. Schedule cardinality depends on catalogue state: an inactive entry
may have none, while an active activity requires one or more weekly or one-off
schedules. `ACTIVITY_CATEGORY` supports classification under several categories
without duplicating catalogue data. Country and city are external UUIDs and do
not appear as locally owned entities.

```mermaid
erDiagram
    ACTIVITY ||--|| LOCATION_DETAILS : "owns"
    ACTIVITY ||--o{ ACTIVITY_AVAILABILITY_SCHEDULE : "inactive zero-or-more; active one-or-more"
    ACTIVITY ||--|{ ACTIVITY_CATEGORY : "is classified through"
    CATEGORY ||--o{ ACTIVITY_CATEGORY : "classifies through"

    ACTIVITY {
        UUID id PK
        string name
        decimal price
        string pricing_basis
        int duration_minutes
        boolean is_active "controls schedule minimum"
    }

    LOCATION_DETAILS {
        UUID id PK
        UUID activity_id FK,UK
        UUID country_id "external reference"
        UUID city_id "external reference"
    }

    CATEGORY {
        string code PK
        string label
        int display_order
    }

    ACTIVITY_CATEGORY {
        UUID activity_id PK,FK
        string category_code PK,FK
    }

    ACTIVITY_AVAILABILITY_SCHEDULE {
        UUID id PK
        UUID activity_id FK
        boolean recurring_weekly
        string day_of_week "nullable"
        date date "nullable"
        time start_time
        time end_time
    }
```
