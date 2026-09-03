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
| `GET /`                    | The whole page, results already rendered                   |
| `GET /accommodation`       | The results fragment: the table and the pager              |
| `GET /accommodation/{id}`  | The details modal for one accommodation                    |
| `POST /accommodation/ai-search` | The results fragment, plus the answer and the filter form out of band |
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
