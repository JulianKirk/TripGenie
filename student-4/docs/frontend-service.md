← Back to [README.md](../../README.md)

# Activities and Attractions Frontend Service

## Service scope

This service renders Student 4's traveller catalogue and management interface. It
talks only to the [Student 4 backend](./backend-service-api.md), never to the
database or shared reference services.

```text
              browser
                 |  :8094 host / :8084 container  HTML
                 v
       student-4-frontend -- Jinja templates + HTMX
                 |  :8008  activity and itinerary-proxy routes
                 v
        student-4-backend
```

The backend returns JSON, while HTMX swaps HTML fragments. The frontend service
therefore owns presentation and translates browser-friendly `GET` parameters
into the backend's structured `QUERY /activity` body. It does not duplicate
database filtering logic.

The page covers both activities and attractions because both are represented
by the single `Activity` model. It intentionally contains no image UI and no
booking or payment workflow.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `BACKEND_URL` | `http://student-4-backend:8008` | Student 4 backend-service base URL. |
| `BACKEND_TIMEOUT` | `5` | Backend request timeout in seconds. |

Run the frontend with:

```bash
docker compose up student-4-frontend
```

Then open `http://localhost:8094`. The separate port keeps the new service
available while the legacy Student 4 placeholder still owns port 8084.

## HTML routes

These routes return pages or fragments, not a public JSON API.

| Route | Returns |
|---|---|
| `GET /` | Unified catalogue and CRUD page, including inactive entries. |
| `GET /activity` | Results-and-pagination HTML fragment. |
| `GET /activity/{id}` | Full activity-detail dialog fragment. |
| `GET /activity/{id}/itineraries/dialog` | Direct trip-picker dialog fragment. |
| `GET /activity/{id}/itineraries` | Itinerary picker fragment from the Student 4 proxy. |
| `PUT /activity/{id}/itineraries/{trip_id}` | Add or reschedule an itinerary selection. |
| `DELETE /activity/{id}/itineraries/{trip_id}` | Remove an itinerary selection. |
| `GET /manage` | Legacy catalogue management page. |
| `GET /manage/activity/new` | Create-activity form fragment. |
| `POST /manage/activity` | Create a complete activity aggregate. |
| `GET /manage/activity/{id}/edit` | Prefilled edit form fragment. |
| `PUT /manage/activity/{id}` | Replace a complete activity aggregate. |
| `GET /manage/activity/{id}/delete` | Permanent-delete confirmation fragment. |
| `DELETE /manage/activity/{id}` | Permanently delete an activity aggregate. |
| `GET /health` | Frontend and backend health JSON. |

`GET /health` returns `200` with `status: "degraded"` when the backend cannot be
reached, matching the other frontend services.

## Page structure

The traveller page has four regions:

1. A heading explaining that attractions and activities share one catalogue.
2. One search-and-filter form.
3. An `aria-live` results region containing create and per-card edit controls,
   cards, count and pager.
4. A dialog target populated when a user opens an activity.

The catalogue includes inactive entries and provides creation, replacement,
deactivation and deletion without requiring a separate management page.

The initial `GET /` concurrently requests the backend's first activity page and
`GET /activity/categories`. Category rows are rendered in the backend-provided
`display_order`. If categories cannot be loaded, the page still renders an
error state instead of presenting a stale hard-coded list.

## Live search

All search controls live in one form:

```html
<form
  id="activity-filters"
  hx-get="/activity"
  hx-trigger="input changed delay:300ms, change"
  hx-target="#activity-results"
  hx-swap="innerHTML"
>
```

The 300 ms debounce applies to typed input. Selects and checkboxes update
immediately through the `change` trigger. The form submits ordinary query
parameters to this frontend route; the frontend builds the JSON body described
by [`QUERY /activity`](./backend-service-api.md#query-activity).

`offset` is not a form control. Pager buttons carry their own offset and use
`hx-include="#activity-filters"`. Changing a filter therefore returns to the
first page automatically.

## Filter controls

| UI control | Frontend parameters | Backend field |
|---|---|---|
| Search box | `text` | `text` |
| Country | `country` | `location.country` |
| City | `city` | `location.city` |
| Street/address text | `street` | `location.street` |
| Category multi-select | repeated `category` | `categories.codes` |
| Category matching | `category_match` | `categories.match` |
| Minimum/maximum price | `price_min`, `price_max` | `price.min`, `price.max` |
| Minimum/maximum duration | `duration_min`, `duration_max` | `duration_minutes.min`, `duration_minutes.max` |
| Party size | `party_size` | `party_size` |
| Youngest/oldest age | `youngest_age`, `oldest_age` | same names |
| Booking | `booking_required` | `booking_required` |
| Accessibility checkboxes | accessibility field names | `accessibility` object |
| Date | `date` | `availability.date` |
| Earliest/latest time | `start_time`, `end_time` | `availability.start_time`, `availability.end_time` |
| Sort | `sort` | `sort` |
| Page size | `limit` | `limit` |

Empty controls are omitted from the backend body; they are never sent as empty
strings or explicit nulls.

### Text and location

The search box matches activity names and descriptions. Country and city use
the public names accepted by the backend. With JavaScript, city is disabled
until a country is present because a city name without its country is
ambiguous. Baseline HTML leaves it enabled so country and city can be submitted
together without JavaScript. The frontend drops an unpaired city server-side
as a second line of defence.

Street is free text because exact addresses belong to Student 4 rather than the
shared location service. It is labelled "Street or address" so it also makes
sense for parks, trails and landmarks without a conventional street number.

### Category selection

Categories appear as a checkbox group populated exclusively from
`GET /activity/categories`, so selecting several values remains
keyboard-accessible without a JavaScript widget. Checkbox values are stable
codes, while visible text uses the corresponding label. Descriptions may be
rendered as supporting help text but are never used as filter values.

An adjacent selector controls whether selected values use `ANY` or `ALL`
matching. `ANY` is the default because it produces the least surprising broad
search. JavaScript disables the control when no category is selected; baseline
HTML keeps it available for progressive enhancement.

### Price, duration and party suitability

Prices are clearly labelled `AUD`; the frontend does not guess a currency from
the activity's location. Money arrives from the backend as an exact two-decimal
string and remains a decimal string when the frontend builds price filters.
Numeric inputs use a `0.01` step and the frontend canonicalizes non-empty values
to two fractional digits, but the backend remains authoritative for validation.

Every displayed price also says `per person` or `flat admission` from the
activity's `pricing_basis`. When a party size is present, the card may show an
estimated party total: `price * party_size` for `PER_PERSON`, or the unchanged
price for `FLAT_ADMISSION`. That calculation uses decimal arithmetic and is
display-only; the backend remains the source of catalogue data.

`party_size` asks whether the activity supports the whole group. Youngest and
oldest ages describe the actual travelling party rather than exposing users to
the model's inverse minimum/maximum comparisons.

### Accessibility and booking

The booking selector has `Any`, `Required externally`, and `No booking
required`. It never offers a booking action.

Accessibility checkboxes mean "require this confirmed feature" and map to
`true`. An activity whose value is unknown does not satisfy the checkbox. The
detail dialog distinguishes `Yes`, `No`, and `Unknown` so missing information is
not misrepresented as inaccessibility.

### Date and time

Date may be used alone. JavaScript enables start and end times once a date is
chosen; baseline HTML leaves them usable. They must be supplied together. The
UI explains that all times are local to the activity.

The frontend does not attempt to expand weekly schedules or determine valid
starts. It sends the requested window to the backend, which applies activity
duration and recurring/one-off schedule rules consistently for every consumer.

## Results

Each result card displays:

- activity name and description;
- country and city when resolvable;
- exact price in AUD, its per-person or flat-admission basis, and duration;
- category labels resolved from the already-loaded category list;
- participant and age restrictions when present;
- external-booking indicator; and
- confirmed accessibility facts.

There are no placeholder images. A card's activity name is a real button whose
`hx-get` loads `GET /activity/{id}` into the dialog target. The returned fragment
uses a native modal `<dialog>` and shows the full description, exact address,
restrictions, booking notes, accessibility notes and availability schedules.

Recurring schedules are grouped by weekday for readability. One-off schedules
show their ISO date. Times remain in local `HH:MM` form. The page does not invent
bookable time slots from a flexible interval.

Each active card has a compact **Add to trip** shortcut that opens the picker
directly, while the detail dialog retains its **Add to trip** or **Manage trip**
action. Each trip has add/update and remove actions plus optional date and
start-time controls. Those actions send `PUT` or `DELETE` to the Student 4
backend. Dates are bounded by each row's returned `start_date` and `end_date`.
The frontend never calls Student 1 directly.

## Catalogue CRUD

The catalogue page includes a coloured **Add new activity** control and an
accessible pen-icon edit action on every card and detail dialog. It uses the
public Student 4 backend only:

| User action | Backend request |
|---|---|
| Create activity | `POST /activity` |
| Load edit form | `GET /activity/{id}` |
| Save complete edit | `PUT /activity/{id}` |
| Deactivate/reactivate | `PUT /activity/{id}` with the full record and changed `is_active` |
| Permanently delete | `DELETE /activity/{id}` after confirmation |
| Show inactive rows | `QUERY /activity` with `include_inactive: true` |

The create/edit form covers every writable field, nested location data,
category checkboxes, and a repeatable schedule editor. It sends country/city
names and strips generated activity, location and schedule ids before writes.
Replacing is a full `PUT`, so the form must send all current writable values;
leaving out an optional value intentionally clears it. Destructive delete has
a confirmation step and deactivation is presented as the safer reversible
choice.

### Itinerary selection

The detail dialog can load the traveller's itineraries through the Student 4
backend. A selection can be added, rescheduled, or removed with an optional
date and local start time. The browser never calls Student 1 directly; Student
4 remains the only API boundary for itinerary changes.

## Catalogue management

`GET /` and its results fragment use the backend query with
`include_inactive: true` so an administrator can see and reactivate hidden
records. The catalogue is paginated using the backend's total, limit, and
offset metadata. Create and edit forms cover the complete activity aggregate:
description, exact price and pricing basis, duration, participant and age
limits, location, categories, booking and accessibility details, activation
state, and weekly or one-off schedules.

Writes are allow-listed and validated into the frontend's strict schema before
being sent to Student 4. The backend remains authoritative for cross-field and
reference-data validation. Edit uses full replacement because the backend API
defines `PUT /activity/{id}`, not a partial patch.

Permanent deletion is reached from the bottom of the edit dialog and requires
a separate confirmation fragment that names the activity and warns that the
action cannot be undone. Deactivation is available through edit; the entry
remains visible and marked inactive in this unified catalogue, but cannot be
newly added to a trip.

## Pagination

The results header shows `total` matches. Previous and next controls calculate
offsets from the response's `limit` and `offset`, retain every active filter via
`hx-include`, and target only the results region.

Controls that would move before zero or beyond `total` are disabled. Backend
ordering is used as returned; the frontend never re-sorts a page locally because
that would make pagination inconsistent.

## Page states and errors

The results region has explicit states for:

- loading;
- no matching activities;
- invalid filter input;
- activity or category data unavailable; and
- malformed upstream data.

Backend `400`, `404`, `502` and `503` responses carry a `detail` value. Request
validation may return a structured list; other errors normally use a string.
The frontend extracts safe client-error text, renders it in the affected
fragment and preserves the form so the user can revise or retry. Network
failures use the same results error region rather than turning into an
unhandled page-level `500`.

A missing detail activity closes or replaces only the dialog. It does not erase
the current search results.

## Accessibility and progressive enhancement

Every input has a visible label; grouped checkboxes use `fieldset` and
`legend`. Results updates are announced through a polite `aria-live` region.
Cards and the detail dialog are keyboard reachable, and status is never
communicated by colour alone.

The initial page and explicit submit button work with ordinary HTTP without
JavaScript. HTMX adds live fragment replacement and pagination. The small
custom script manages dependent controls, repeatable schedule rows, modal
dialog lifecycle, and close actions; the server repeats all validation checks.

## Frontend boundaries

The frontend:

- does not call the Student 4 database service;
- does not call the shared reference service;
- does not implement activity filtering or schedule calculations;
- does not maintain a separate category list;
- does not create bookings, take payments or track availability inventory;
- performs catalogue CRUD only through the Student 4 backend; and
- performs itinerary selection only through the Student 4 backend.
