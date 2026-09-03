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
| `AI_TIMEOUT`      | `210`                           | Seconds to wait on the ask box alone, which waits on a model |

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
| `POST /accommodation/ai-search` | The results fragment, plus the answer and the filter form out of band |
| `GET /accommodation/{id}/stay` | The Add-to-Trip form, as a second modal. Re-renders itself on every change to recompute the total |
| `PUT /accommodation/{id}/itineraries/{itineraryId}` | Stores the stay from the form body |
| `GET /accommodation/new`   | An empty create form, as a modal                           |
| `GET /accommodation/{id}/edit` | The same form, filled in with what is stored           |
| `POST /accommodation`      | Saves a new accommodation from the form body               |
| `PUT /accommodation/{id}`  | Saves an edit from the form body                           |
| `DELETE /accommodation/{id}` | Deletes an accommodation                                 |
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

### Creating, editing and deleting

**Add accommodation** in the masthead fetches `GET /accommodation/new` into
`#form-modal`; **Edit** in the details modal fetches `GET /accommodation/{id}/edit`
into the same place. One template serves both — they differ only in where the
form posts and what it starts out holding, so there is nothing to keep in step
between two of them.

`#form-modal` is its own container rather than the details modal's `#modal`,
because an edit opens *over* the details dialog and closing the form has to
leave that one standing.

The form posts as an ordinary HTML form body; this service turns it into the
accommodation message the backend documents, over the same field maps the
filter form uses (`app.py`). Blank inputs are dropped rather than sent — an
empty box is "not given", not an empty string to store. Numbers stay strings on
the way out: the backend's schema coerces them, and deciding what a half-typed
`12.` means is a decision worth making once.

Because the backend's `PUT` is a merge with no way to unset a field, an emptied
input on the edit form keeps the stored value. The form says so rather than
looking like it lost it.

On success the response body is nothing but out-of-band fragments, so the swap
that targets the form's `<dialog>` replaces it with nothing — which is what
closes it. The same fragment clears `#modal`, since after an edit or a delete
what it is showing is stale or gone, and drops a toast into `#page-toast` at
page level (a toast inside a dialog that has just been removed goes with it).

The refreshed list is **not** in that fragment. The response carries
`HX-Trigger: accommodations-changed`, and the filter form listens for it:

```html
hx-trigger="input changed delay:300ms, change, accommodations-changed from:body"
```

So the list comes back through the filters actually on screen — which a fragment
rendered by a write route could not know. A rejected save re-renders the form
instead, carrying the backend's message and everything that was typed.

Delete asks first, with `hx-confirm`, because it cannot be undone.

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

### The ask box

Above the filter form: one input, one button, and a question in English.

```html
hx-post="/accommodation/ai-search" hx-target="#results" hx-swap="innerHTML"
```

The backend turns the question into filters and runs the ordinary search (see
[POST /accommodation/ai-search](./backend-service-api.md#post-accommodationai-search)),
so what comes back is the same `partials/results.html` every other search
renders. Two things come back with it, both swapped **out of band**: the answer
-- the model's own sentence, and a line saying how the question was read as
filters -- which lands in `#ai-answer` under the ask box rather than in the
results, because it answers the question rather than being one of the results;
and the filter form itself:

```html
<form id="filters" class="filters" hx-swap-oob="true" ...>
```

An ordinary search, filter change or pager link swaps `#ai-answer` back to
empty the same way (`partials/search_results.html`): once the page has been
searched by hand, the answer is no longer what the results are.

While the request is in flight `#asking` is visible -- a label and a bar that
slides. It is indeterminate on purpose: a generation reports no progress, so a
bar that pretended to know would be lying. What it is there to say is that a
20-second wait on a local model is a wait and not a hang. `prefers-reduced-
motion` gets a full, still bar instead.

That out-of-band swap is the whole design. After asking a question the page is
in exactly the state it would be in had you typed those filters by hand, so the
pager (which pulls its filters off the form with `hx-include="#filters"`), the
details modal and every manual filter carry on working with no special case for
having asked. It also makes the model's reading visible and editable rather than
hidden -- if it misread the question, the wrong filter is sitting right there to
fix.

The form's fields moved into `partials/filters.html` so both paths render the
one template. It reads a `QueryParams` either way: the real one on a `GET`, and
one built from the answer by `form_values()` -- the inverse of `query_body()`,
over the same four field maps, so a filter's form name and message name are
paired up in exactly one place.

A blank ask is the unfiltered list, not an error, the same answer an empty
search box gives. An AI failure renders in `partials/error.html` where the
results would have been, like every other backend failure, and the ask box is
gone but nothing else on the page is.

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
