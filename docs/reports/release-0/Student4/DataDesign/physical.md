# Student 4 Physical Data Design

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

- [`models.py`](../../../../../student-4/database/student4_database_service/models.py)
- [`database.py`](../../../../../student-4/database/student4_database_service/database.py)
- [`enums.py`](../../../../../student-4/database/student4_database_service/enums.py)
- [`object-model.md`](../../../../../student-4/docs/object-model.md)
