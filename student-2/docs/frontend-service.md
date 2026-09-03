← Back to [README.md](../../README.md)

# Accommodation Frontend Service

The accommodation webpage. It talks to the
[backend service](./backend-service-api.md) and nothing else; it never reaches
the database service.

```
                browser
                   │  :9003
                   ▼
        student-2-frontend  ── Jinja templates + HTMX
                   │  :9000  GET|QUERY /accommodation
                   ▼
         student-2-backend
```

## Why there is a service here at all

HTMX swaps **HTML fragments** returned by a server, and the backend serves JSON,
so something has to render the rows. Two further constraints settle it:

- The only filtered search the backend offers is `QUERY /accommodation` with a
  JSON body. HTMX issues `GET`/`POST`/`PUT`/`PATCH`/`DELETE` and nothing else,
  so the filter form arrives here as query parameters and leaves as that body.
- `GET /accommodation` takes pagination only, no filters.

## Configuration

| Variable          | Default                         | Purpose                                  |
|-------------------|---------------------------------|------------------------------------------|
| `BACKEND_URL`     | `http://student-2-backend:9000` | Base URL of the backend service          |
| `BACKEND_TIMEOUT` | `5`                             | Seconds to wait on a backend call        |

## Running it

```bash
docker compose up student-2-frontend
```

Then open <http://localhost:9003>.

## Routes

These serve HTML, not an API — no other service is a caller.

| Route                      | Returns                                                    |
|----------------------------|------------------------------------------------------------|
| `GET /`                    | The whole page, results already rendered. `?accommodation=<id>` opens that one's modal with the page |
| `GET /accommodation`       | The results fragment: the table and the pager              |
| `GET /accommodation/{id}`  | The details modal for one accommodation                    |
| `GET /accommodation/{id}/stay` | The Add-to-Trip form, as a second modal. Re-renders itself on every change to recompute the total |
| `PUT /accommodation/{id}/itineraries/{itineraryId}` | Stores the stay from the form body |
| `GET /health`              | `{"status", "service", "backend"}`                         |

`/health` reports `degraded` (still `200`) when the backend is unreachable —
the same convention the backend uses for the database service.

## The page

Every control — the search box, every filter, the page-size select — lives in
one `<form id="filters">` with a single HTMX trigger on it:

```html
hx-get="/accommodation" hx-trigger="input changed delay:300ms, change"
hx-target="#results" hx-swap="innerHTML"
```

That one line is the whole of search-as-you-type (300 ms debounce) and the
live filtering. There is no per-input wiring and, apart from the city/country
pairing described below, no JavaScript.

`offset` is deliberately **not** a form field; only the pager buttons carry one,
and they pull the filters off the form with `hx-include="#filters"`. So changing
any filter drops you back to page one for free.

Clicking a row swaps `GET /accommodation/{id}` into `#modal`, which renders a
native `<dialog open>` — focus handling, Escape and the backdrop come from the
browser rather than from a modal library. The row's name is a real `<button>`,
so the modal is reachable without a mouse.

### Linking to one accommodation

`GET /?accommodation=<id>` renders the page with that accommodation's modal
already open. Student 1's trip page links here from each row of its
Accommodation section — the modal is a fragment, so a bare link to
`/accommodation/{id}` would hand the browser a page with no page around it. An
id the service does not know still returns the list, with a note above it: the
link came from another service's data, and a stale one is not a reason to lose
the page.

### Adding one to a trip

The details modal carries an **Add to Trip** button and nothing else about
trips. Pressing it fetches `GET /accommodation/{id}/stay` into `#stay-modal`, a
second `<dialog>` that opens over the first. Both sit in the browser's top
layer, so the form stacks above the details without a `z-index` of ours, and
closing it (Escape, Cancel, or the ×) leaves the details modal untouched
underneath.

The form asks for the trip, a check-in date and time, and a check-out date and
time. The two dates are bounded by the chosen trip's own window, so the native
calendar cannot offer a date the trip service would reject.

**The nightly total is server-side arithmetic.** A wrapper inside the form
carries `hx-trigger="change from:closest form"` and `hx-include="closest form"`,
so any change re-renders the whole form — with the new total, and with the date
bounds of whichever trip is now selected. The price is `price_per_night ×
nights`, where nights is the gap between the two dates:

| State | Shown |
| --- | --- |
| No check-out yet | "Pick a check-out date for the total." |
| Same day | "Same-day stay — no nights, no charge." |
| *n* nights | The total, with `n nights × $rate` as its working |
| No `price_per_night` | "No nightly rate recorded, so there is no total to show." |

ponytail: doing this on the server rather than in a script means the number on
screen is the same arithmetic the rest of the page uses, and there is no
JavaScript on the form at all — `<input type="date">` and `type="time"` bring
their own pickers, keyboard handling and mobile UI.

On success the response body is *only* an out-of-band toast: the main swap
replaces the form's `<dialog>` with nothing, which is what closes it. The toast
goes out-of-band into `#modal-toast` inside the details dialog, because it is
`position: fixed` and only a descendant of an open modal paints above that
modal's backdrop — left where the form was, it would be swapped away in the
same breath.

A rejected stay re-renders the form with the message inside it and every value
still in the inputs.

**Not offered here:** taking an accommodation back off a trip. The tick-list
that carried that control is gone, so removal is currently only reachable
through the backend's `DELETE` endpoint or student 1's own trip page.

### Filters

One per property the backend can filter on: `name` (the search box),
`description`, `type`, `availability_status`, `amenities` (checkboxes, all of
them must be present), `country`, `city`, `street`, `street_number`,
`room_count`, `bed_count`, room description, plus the range bounds
`price_min`/`price_max`, `rating_min`/`rating_max`, `room_count_min` and
`bed_count_min`.

Not offered: `room_details.bed_types`, which the database service cannot filter
on, and `id`, since a row is opened by clicking it.

The backend rejects a `city` without a `country` ("Sydney" is ambiguous), so the
city input stays disabled until a country is typed and an unpaired city is
dropped server-side as well. That is the one piece of script on the page.

### Errors

A `400`/`404`/`502`/`503` from the backend carries `{"detail": ...}`, and that
text is rendered where the results would have been. An unreachable backend says
so in the same place. The page never 500s because the backend did.

ponytail: no pydantic mirror of the accommodation message and no client module
here — the decoded JSON goes straight into the templates. Add models when this
service starts computing on the data rather than displaying it.
