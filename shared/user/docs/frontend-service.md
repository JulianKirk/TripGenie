← Back to [user-service.md](../user-service.md)

# User Frontend Service

## Service Scope

This service runs on `http://localhost:9103`. It is the sign-in page and the
account page, and it talks to the backend service and nothing else — it never
reaches the database service.

```
browser ──► frontend (you are here) ──► backend ──► database
```

It exists for the same reason student 2's does: the backend speaks JSON and a
browser posts form-encoded bodies, so something has to translate. It renders
Jinja templates server-side and holds no state of its own.

### Running it

```bash
docker compose up shared-user-frontend
```

That starts the backend and database behind it too. To run the image alone:

```bash
docker build -f shared/user/frontend/Dockerfile -t shared-user-frontend shared/user
docker run --rm -p 9103:9103 shared-user-frontend
```

With no backend reachable, `/health` answers `degraded` with a `200` and every
page shows "The account service is not responding."

### Configuration

| Variable          | Default                            | Purpose                                   |
|-------------------|------------------------------------|-------------------------------------------|
| `BACKEND_URL`     | `http://shared-user-backend:9100`  | The only service this one calls           |
| `BACKEND_TIMEOUT` | `5`                                | Seconds before a call is treated as down  |

## Routes

| Route | What it does |
| --- | --- |
| `GET /` | The sign-in page: a sign-in form and a sign-up form. Calls nothing — there is nothing to fetch until someone types. |
| `POST /login` | → `POST /users/login`. On success, `303` to `/account/{id}`. On failure, re-renders the page with the error. |
| `POST /signup` | → `POST /users`. Same redirect on success; on a `409`, re-renders with "username already taken". |
| `GET /account/{id}` | → `GET /users/{id}`. The account page. An unknown or stale id redirects to `/` rather than showing an error. |
| `POST /account/{id}` | → `PUT /users/{id}`. Swaps the edit form back in with the result. **The only HTMX route.** |
| `POST /account/{id}/delete` | → `DELETE /users/{id}`, then `303` to `/`. |
| `GET /health` | This service and the backend behind it. Always `200`. |

## Pages

**`/` — sign in.** Two cards side by side, sign in and sign up. Both are plain
HTML form posts. A failed sign-in comes back with the username still filled in
and the password field empty: the username saves retyping, the password should
not be sitting in the page it just failed on.

**`/account/{id}` — the account.** The username as the page heading, a form to
change the username and/or password, a "sign out" link, and a delete button
behind a `confirm()`.

- The password field is blank with a "leave blank to keep the current one"
  placeholder. Blank fields are dropped rather than sent — an empty password
  box means "leave it alone", not "set my password to the empty string". If
  both are blank the backend is not called at all.
- After a save, the form is re-rendered with the username **the backend
  returned**, never the one that was typed, so the page cannot show a change
  that did not happen.
- "Sign out" is a link back to `/`. There is no session to end.

## Why only one HTMX route

Sign in, sign up and delete all end in a redirect to a different page. A
redirect through HTMX needs an `HX-Redirect` response header and a bit of
client-side handling, and buys nothing when the whole page is changing anyway —
so those three are plain form posts with a `303`.

The account edit is the one interaction where only part of the page changes, so
it is the one that uses `hx-post`/`hx-swap`, swapping the form and its
saved/error message back into `#account`.

## Errors

There is no error page. Every failure is rendered in place:

- On the sign-in page, in a `notice--error` above whichever form failed.
- On the account page, in the same notice inside the swapped-in form.
- An unreachable backend shows "The account service is not responding. Try
  again shortly." rather than the raw error.

The backend's `{"detail": ...}` string is shown to the user directly — its
messages ("username already taken", "invalid username or password") are already
written to be read by a person.

## Sessions

There are none. `POST /login` redirects to `/account/{id}` and the id in that
URL is the entire notion of who is signed in. Anyone holding the URL is that
user; closing the tab is signing out. This is deliberate for the release — see
the note in [user-service.md](../user-service.md) — and `app.py` carries the
`ponytail:` comment saying it is this module that grows the cookie when it
stops being true.
