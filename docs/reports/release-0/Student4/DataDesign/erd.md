# Student 4 Entity-Relationship Diagram

The ERD resolves the many-to-many activity/category relationship through
`ACTIVITY_CATEGORY`. Location is a one-to-one owned entity, while schedules
are one-to-many children of an activity.

```mermaid
erDiagram
    ACTIVITY ||--|| LOCATION_DETAILS : "owns"
    ACTIVITY ||--o{ ACTIVITY_AVAILABILITY_SCHEDULE : "offers"
    ACTIVITY ||--|{ ACTIVITY_CATEGORY : "is classified through"
    CATEGORY ||--o{ ACTIVITY_CATEGORY : "classifies through"

    ACTIVITY {
        UUID id PK
        string name
        decimal price
        string pricing_basis
        int duration_minutes
        boolean is_active
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
