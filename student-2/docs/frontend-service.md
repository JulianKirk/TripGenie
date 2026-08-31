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
