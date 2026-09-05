# Student 4 Physical Data Design

The database service is the only component that reads this SQLite database.
SQLAlchemy stores UUIDs as 32-character values and stores prices as canonical
decimal text so filtering and API serialization never introduce binary
floating-point errors. Owned locations, schedules and category links cascade
when an activity is deleted; the alias table exists only to resolve legacy seed
identifiers and intentionally has no database foreign key.

```mermaid
erDiagram
    ACTIVITIES ||--o| LOCATION_DETAILS : "DB zero-or-one; API exactly one"
    ACTIVITIES ||--o{ ACTIVITY_AVAILABILITY_SCHEDULES : "DB zero-or-more; active API one-or-more"
    ACTIVITIES ||--o{ ACTIVITY_CATEGORIES : "DB zero-or-more; API one-or-more"
    CATEGORIES ||--o{ ACTIVITY_CATEGORIES : "FK"
    ACTIVITIES ||..o{ ACTIVITY_ID_ALIASES : "service lookup only; no FK"

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

SQLite foreign keys enforce child-to-parent references and cascade deletion,
but they cannot require a parent activity to have child rows. The API validation
therefore requires one location, at least one category, and at least one
schedule whenever `is_active` is true. The database still permits an inactive
catalogue entry to have no schedules.

The physical indexes support country/city filtering, category-first lookup,
schedule lookup by activity, and activity lookup from a legacy alias. Two
partial unique indexes prevent duplicate weekly and one-off schedule rows.
SQLite `CHECK` constraints enforce enum values, canonical prices, valid
booleans, ordered bounds, non-negative values, valid local date/time text, and
the weekly-versus-one-off schedule discriminator. The service additionally
checks that each schedule interval can contain the activity's full duration.

## Implementation sources

- [`models.py`](../../../../../student-4/database/student4_database_service/models.py)
- [`database.py`](../../../../../student-4/database/student4_database_service/database.py)
- [`enums.py`](../../../../../student-4/database/student4_database_service/enums.py)
- [`object-model.md`](../../../../../student-4/docs/object-model.md)
