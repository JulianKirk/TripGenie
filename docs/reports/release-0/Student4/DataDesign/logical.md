# Student 4 Logical Data Model (ERD)

The fields support catalogue search and the planning information consumed by
the itinerary and budget services. Prices are exact AUD values and
`pricing_basis` determines whether a party cost is per person or a single flat
admission charge. Nullable accessibility flags deliberately distinguish an
unknown value from a confirmed `false` value.

This implementation-neutral ERD shows every business attribute, logical data
type, key and relationship, but not SQLite storage details, indexes or
implementation-only compatibility tables. A high-resolution
[PNG export](logical.png) is included alongside this document.

```mermaid
%%{init: {"theme":"base","themeVariables":{"fontFamily":"Inter, ui-sans-serif, system-ui, sans-serif","primaryColor":"#eff6ff","primaryTextColor":"#0f172a","primaryBorderColor":"#2563eb","lineColor":"#475569","tertiaryColor":"#f8fafc"}}}%%
erDiagram
    ACTIVITY ||--|| LOCATION_DETAILS : "has"
    ACTIVITY ||--o{ ACTIVITY_AVAILABILITY_SCHEDULE : "inactive zero-or-more; active one-or-more"
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
        boolean is_active "controls schedule minimum"
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

The principal logical rules are: every activity has at least one category;
every active activity has at least one schedule; duration must be positive; age
and party bounds must be ordered; end time must follow start time; and each
schedule must provide either a weekday or a date according to
`recurring_weekly`, never both.
