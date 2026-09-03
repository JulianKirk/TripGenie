← Back to [README.md](../../README.md)

# Activities and Attractions Frontend Service

## Service scope

This document is the implementation contract for Student 4's future
activities-and-attractions webpage. The current backend-focused branch does not
implement that frontend; `student-4-service` remains a placeholder static
server. When implemented, the frontend talks only to the
[Student 4 backend](./backend-service-api.md), never to the database or shared
reference services.

```text
              browser
                 |  :8084  HTML GET
                 v
       student-4-frontend -- Jinja templates + HTMX
                 |  :8008  GET|QUERY /activity
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

Run the backend and its dependencies with:

```bash
docker compose up student-4-backend
```

Open `http://localhost:8008/docs` to inspect and exercise the backend contract.
Port `8084` does not provide the UI described below until the frontend is
implemented on its own branch.

## HTML routes

These routes return pages or fragments, not a public JSON API.

| Route | Returns |
|---|---|
| `GET /` | Full page with filters, category options and first result page. |
| `GET /activity` | Results-and-pagination HTML fragment. |
| `GET /activity/{id}` | Full activity-detail dialog fragment. |
| `GET /health` | Frontend and backend health JSON. |

`GET /health` returns `200` with `status: "degraded"` when the backend cannot be
reached, matching the other frontend services.

## Page structure

The page has five regions:

1. A heading explaining that attractions and activities share one catalogue.
2. One search-and-filter form.
3. An `aria-live` results region containing cards, count and pager.
4. A dialog target populated when a user opens or edits an activity.
5. An administration region for creating, replacing, deactivating and deleting
   catalogue entries.

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
the public names accepted by the backend. City remains disabled until a country
is present, because a city name without its country is ambiguous. The frontend
drops an unpaired city server-side as a second line of defence.

Street is free text because exact addresses belong to Student 4 rather than the
shared location service. It is labelled "Street or address" so it also makes
sense for parks, trails and landmarks without a conventional street number.

### Category dropdown

Categories appear in a multi-select dropdown populated exclusively from
`GET /activity/categories`. The dropdown uses a native disclosure containing a
labelled checkbox for each category, so selecting several values remains
keyboard-accessible without a JavaScript widget. Checkbox values are stable
codes, while visible text uses the corresponding label. Descriptions may be
rendered as supporting help text but are never used as filter values.

An adjacent selector controls whether selected values use `ANY` or `ALL`
matching. `ANY` is the default because it produces the least surprising broad
search. The control is disabled when no category is selected.

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

Date may be used alone. Start and end times are enabled only once a date is
chosen and must be supplied together. The UI explains that all times are local
to the activity.

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
uses a native `<dialog open>` and shows the full description, exact address,
restrictions, booking notes, accessibility notes and availability schedules.

Recurring schedules are grouped by weekday for readability. One-off schedules
show their ISO date. Times remain in local `HH:MM` form. The page does not invent
bookable time slots from a flexible interval.

Every card and detail dialog also offers an **Add to itinerary** button. It
loads `GET /activity/{id}/itineraries` from the Student 4 backend, shows each
trip with a checkbox plus date and optional start-time controls, and sends
`PUT` or `DELETE` to that same Student 4 backend. Dates are bounded by each
row's returned `start_date` and `end_date`. The frontend never calls Student 1
directly.

## Catalogue CRUD

The page includes a clearly separated management mode. It uses the public
Student 4 backend only:

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

Backend `400`, `404`, `502` and `503` responses carry `{"detail": "..."}`. The
frontend renders a safe text message in the affected fragment and preserves the
form so the user can revise or retry. Network failures use the same results
error region rather than turning into an unhandled page-level `500`.

A missing detail activity closes or replaces only the dialog. It does not erase
the current search results.

## Accessibility and progressive enhancement

Every input has a visible label; grouped checkboxes use `fieldset` and
`legend`. Results updates are announced through a polite `aria-live` region.
Cards and the detail dialog are keyboard reachable, and status is never
communicated by colour alone.

The initial page and explicit submit button work with ordinary HTTP without
JavaScript. HTMX adds live fragment replacement and pagination. The only custom
script required is the small dependency rule that disables city without country
and prevents a partial start/end time pair; the server repeats both checks.

## Frontend boundaries

The frontend:

- does not call the Student 4 database service;
- does not call the shared reference service;
- does not implement activity filtering or schedule calculations;
- does not maintain a separate category list;
- does not create bookings, take payments or track availability inventory; and
- performs catalogue CRUD only through the Student 4 backend; and
- performs itinerary selection only through the Student 4 backend.
