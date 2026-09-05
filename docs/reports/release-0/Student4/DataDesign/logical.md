# Student 4 Logical Data Design

The logical model is independent of SQLite storage types. It includes the
complete business data and identifies optional values, keys, and controlled
enumerations used by the service contract.

```mermaid
erDiagram
    ACTIVITY ||--|| LOCATION_DETAILS : "has"
    ACTIVITY ||--o{ ACTIVITY_AVAILABILITY_SCHEDULE : "has"
    ACTIVITY ||--|{ ACTIVITY_CATEGORY : "has"
    CATEGORY ||--o{ ACTIVITY_CATEGORY : "is assigned by"

    ACTIVITY {
        UUID id PK
        string name
        string description
        decimal price "AUD, two decimal places"
        PricingBasis pricing_basis "PER_PERSON or FLAT_ADMISSION"
        integer duration_minutes
        integer minimum_age "optional"
        integer maximum_age "optional"
        integer minimum_participants
        integer maximum_participants "optional"
        boolean booking_required
        string booking_notes "optional"
        boolean wheelchair_accessible "optional; unknown allowed"
        boolean step_free_access "optional; unknown allowed"
        boolean accessible_toilet "optional; unknown allowed"
        string accessibility_notes "optional"
        boolean is_active
    }

    LOCATION_DETAILS {
        UUID id PK
        UUID activity_id FK,UK
        UUID country_id "shared-service identifier"
        UUID city_id "shared-service identifier"
        string street "optional"
        integer street_number "optional"
    }

    CATEGORY {
        CategoryCode code PK
        string label
        string description "optional"
        integer display_order
    }

    ACTIVITY_CATEGORY {
        UUID activity_id PK,FK
        CategoryCode category_code PK,FK
    }

    ACTIVITY_AVAILABILITY_SCHEDULE {
        UUID id PK
        UUID activity_id FK
        boolean recurring_weekly
        DayOfWeek day_of_week "weekly only"
        date date "one-off only"
        time start_time
        time end_time
    }
```

The principal logical rules are: duration must be positive; age and party
bounds must be ordered; every category assignment must reference a seeded
category; end time must follow start time; and each schedule must provide
either a weekday or a date according to `recurring_weekly`, never both.
