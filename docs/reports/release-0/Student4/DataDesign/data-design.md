# Student 4 Data Design

Student 4 owns TripGenie's Activities and Attractions catalogue. The service
stores activity aggregates in its own SQLite database and exposes them through
the Student 4 database and backend APIs. Country and city records remain owned
by the shared reference service; Student 4 stores their UUIDs but does not join
across service databases. These diagrams describe the implemented Release 0
model at progressively more concrete levels.

## Conceptual diagram

The conceptual model shows the business concepts without database-specific
attributes. An activity occurs at one location, belongs to one or more
categories, and may have multiple recurring or one-off availability schedules.

```mermaid
flowchart LR
    ACTIVITY[Activity]
    LOCATION[Location details]
    CATEGORY[Category]
    SCHEDULE[Availability schedule]
    PLACE[Shared country and city]

    ACTIVITY -->|takes place at exactly one| LOCATION
    ACTIVITY <-->|classified by one or more| CATEGORY
    ACTIVITY -->|has zero or more| SCHEDULE
    LOCATION -.->|references by UUID| PLACE
```

An inactive draft may have no schedule. An active activity must have at least
one schedule. The dotted connection represents a cross-service reference, not
a local database relationship.

## Entity-relationship diagram (ERD)

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

## Logical diagram

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

## Physical diagram

The physical model reflects the SQLAlchemy-generated SQLite schema. UUIDs are
stored as 32-character values, money is canonical decimal text, booleans use
SQLite boolean affinity with checks, and foreign-key cascading is enabled for
owned rows.

```mermaid
erDiagram
    ACTIVITIES ||--|| LOCATION_DETAILS : "FK cascade"
    ACTIVITIES ||--o{ ACTIVITY_AVAILABILITY_SCHEDULES : "FK cascade"
    ACTIVITIES ||--|{ ACTIVITY_CATEGORIES : "FK cascade"
    CATEGORIES ||--o{ ACTIVITY_CATEGORIES : "FK"
    ACTIVITIES ||--o{ ACTIVITY_ID_ALIASES : "service lookup; no FK"

    ACTIVITIES {
        CHAR32 id PK "CHAR(32)"
        VARCHAR name "NOT NULL"
        VARCHAR description "NOT NULL"
        VARCHAR price "canonical decimal text"
        VARCHAR14 pricing_basis "checked enum"
        INTEGER duration_minutes "NOT NULL"
        INTEGER minimum_age "NULL"
        INTEGER maximum_age "NULL"
        INTEGER minimum_participants "NOT NULL"
        INTEGER maximum_participants "NULL"
        BOOLEAN booking_required "NOT NULL"
        VARCHAR booking_notes "NULL"
        BOOLEAN wheelchair_accessible "NULL"
        BOOLEAN step_free_access "NULL"
        BOOLEAN accessible_toilet "NULL"
        VARCHAR accessibility_notes "NULL"
        BOOLEAN is_active "NOT NULL"
    }

    LOCATION_DETAILS {
        CHAR32 id PK "CHAR(32)"
        CHAR32 activity_id FK,UK "ON DELETE CASCADE"
        CHAR32 country_id "external UUID"
        CHAR32 city_id "external UUID"
        VARCHAR street "NULL"
        INTEGER street_number "NULL"
    }

    CATEGORIES {
        VARCHAR10 code PK "checked enum"
        VARCHAR label "NOT NULL"
        VARCHAR description "NULL"
        INTEGER display_order "NOT NULL"
    }

    ACTIVITY_CATEGORIES {
        CHAR32 activity_id PK,FK "ON DELETE CASCADE"
        VARCHAR10 category_code PK,FK
    }

    ACTIVITY_AVAILABILITY_SCHEDULES {
        CHAR32 id PK "CHAR(32)"
        CHAR32 activity_id FK "ON DELETE CASCADE"
        BOOLEAN recurring_weekly "NOT NULL"
        VARCHAR9 day_of_week "NULL; checked enum"
        DATE date "NULL"
        TIME start_time "NOT NULL"
        TIME end_time "NOT NULL"
    }

    ACTIVITY_ID_ALIASES {
        CHAR32 alias_id PK "legacy seed UUID"
        CHAR32 activity_id "indexed; no database FK"
    }
```

The physical indexes support country/city filtering, category-first lookup,
schedule lookup by activity, and activity lookup from a legacy alias. Two
partial unique indexes prevent duplicate weekly and one-off schedule rows.
SQLite `CHECK` constraints enforce enum values, canonical prices, valid
booleans, ordered bounds, non-negative values, valid local date/time text, and
the weekly-versus-one-off schedule discriminator. The service layer additionally
enforces aggregate rules that require parent-row context, including schedule
duration and the active-activity requirements.

## Implementation sources

- [`student-4/database/student4_database_service/models.py`](../../../../../student-4/database/student4_database_service/models.py)
- [`student-4/database/student4_database_service/database.py`](../../../../../student-4/database/student4_database_service/database.py)
- [`student-4/database/student4_database_service/enums.py`](../../../../../student-4/database/student4_database_service/enums.py)
- [`student-4/docs/object-model.md`](../../../../../student-4/docs/object-model.md)
