← Back to [user-service.md](../user-service.md)

### Table of Contents

- [Service Endpoints](#service-endpoints)
  - [GET /health](#get-health)
- [User Endpoints](#user-endpoints)
  - [GET /internal/users/{id}](#get-internalusersid)
  - [GET /internal/users](#get-internalusers)
  - [POST /internal/users](#post-internalusers)
  - [PUT /internal/users/{id}](#put-internalusersid)
  - [DELETE /internal/users/{id}](#delete-internalusersid)

# User Database Service API

## Service Scope

This service runs on `http://shared-user-database:9101`. It is internal-only —
not exposed to end users or the frontend directly. The only caller is the
backend service. The `curl` examples below use `localhost:9101`, which assumes
the service is run directly rather than inside the compose network.

```
frontend ──► backend ──► database (you are here) ──► SQLite
```

ponytail: no service-to-service auth while the database service is unpublished
on the compose network and the backend is the sole caller. Add a shared bearer
token when the service gains a published port or a second caller.

**This service stores and returns passwords in plaintext.** That is deliberate
for this release — see the note in [user-service.md](../user-service.md). It is
also why the backend's copy of the user message has no password field: the
plaintext stops at the service boundary.

### Running it

```bash
docker compose up shared-user-database
```

Compose `expose`s port 9101 without publishing it, so the service is reachable
by name from other containers but not from the host. To reach it from the host
(to run the `curl` examples below), run the image directly:

```bash
docker build -f shared/user/database/Dockerfile -t shared-user-database shared/user
docker run --rm -p 9101:9101 shared-user-database
```

The SQLite database lives at `$DATABASE_URL` (default `/data/user.db` in the
image, on the `shared-user-db` volume). Tables are created on startup, and an
*empty* database is then filled with the starter accounts in
`database_service/seed_data.py` — otherwise there is no account to sign in with
at all. A database that already has rows is left alone. Set `SEED_DATA=0` to
skip it; the tests do.

### Configuration

| Variable       | Default                                 | Purpose                                             |
|----------------|-----------------------------------------|-----------------------------------------------------|
| `DATABASE_URL` | `sqlite:///shared/user/database/user.db` | SQLite path (`/data/user.db` in the image)          |
| `SEED_DATA`    | `1`                                     | Seed an empty database on startup; `0` to skip      |

### The user message

There is one user shape, and every field on it is nullable — the same protobuf
convention student 2's services use. The same message is the `PUT` body and the
response body of every endpoint; what differs is which fields are filled in.

```json
{
  "id": "3f1c8b52-8f8e-4a3d-9f2e-0b7c1d9a4e11",
  "username": "mark",
  "password": "hunter2"
}
```

- **Responses omit what they did not set.** A field that is not populated is
  absent from the JSON rather than present as `null`. `POST` returns a user
  carrying only `id` and `username`; `GET` returns one carrying everything.
- **Unknown fields are rejected.** The message is `extra="forbid"`, so a typo
  in a field name is a `400` rather than a silently ignored value.
- **`PUT` is a merge.** Only the fields present in the body are changed. There
  is no documented way to unset a field — neither of them has a meaningful
  empty value.

### Errors

| Status | When |
| --- | --- |
| `400` | Invalid input: a missing required field, an empty string, an unknown field, a malformed body |
| `404` | No user with that id |
| `409` | The username is already taken |

Error bodies are FastAPI's `{"detail": ...}`. The `400` carries the validation
error list; the `404` and `409` carry a string.

The `409` is worth knowing about: it comes from the `UNIQUE` constraint on
`username`, translated in one exception handler, so **both** `POST` and `PUT`
can answer it. There is no read-then-write check anywhere — the constraint is
the only thing that can answer the question without a race.

---

## Service Endpoints

### GET /health

Liveness. Opens and closes a database connection; does not query.

```bash
curl localhost:9101/health
```

```json
{ "status": "ok", "service": "shared-user-database" }
```

---

## User Endpoints

### GET /internal/users/{id}

One user, in full — **including the password**, which is what makes a login
possible one layer up.

| Path Parameter | Type | Notes |
| --- | --- | --- |
| `id` | UUID | Must be a well-formed UUID, or the route does not match (`404`) |

```bash
curl localhost:9101/internal/users/3f1c8b52-8f8e-4a3d-9f2e-0b7c1d9a4e11
```

```json
{
  "id": "3f1c8b52-8f8e-4a3d-9f2e-0b7c1d9a4e11",
  "username": "mark",
  "password": "hunter2"
}
```

| Status | When |
| --- | --- |
| `404` | No user with that id |

---

### GET /internal/users

A page of users, optionally filtered to one username. **This is the lookup a
login is**: the backend asks for the username, gets the row with its password,
and does the comparison itself.

| Query Parameter | Type | Default | Notes |
| --- | --- | --- | --- |
| `username` | string | — | **Exact** match, not a substring. `mar` does not find `mark`. |
| `limit` | int | `20` | 1–100 |
| `offset` | int | `0` | ≥ 0 |

ponytail: a GET with a query parameter rather than student 2's `QUERY` with a
body — one exact-match filter does not need a request body. Switch to `QUERY`
when there is more than one field to send.

```bash
curl "localhost:9101/internal/users?username=mark"
```

```json
{
  "users": [
    {
      "id": "3f1c8b52-8f8e-4a3d-9f2e-0b7c1d9a4e11",
      "username": "mark",
      "password": "hunter2"
    }
  ],
  "total": 1
}
```

An unknown username is an empty page, not a `404`:

```json
{ "users": [], "total": 0 }
```

---

### POST /internal/users

Create an account. `username` and `password` are both required.

```bash
curl -X POST localhost:9101/internal/users \
  -H 'content-type: application/json' \
  -d '{"username": "mark", "password": "hunter2"}'
```

`201`, carrying only what the caller needs to find the row again:

```json
{ "id": "3f1c8b52-8f8e-4a3d-9f2e-0b7c1d9a4e11", "username": "mark" }
```

| Status | When |
| --- | --- |
| `400` | Missing or empty `username`/`password`, or an unknown field |
| `409` | The username is already taken |

---

### PUT /internal/users/{id}

Change the username, the password, or both. A merge: omitted fields are left
alone.

```bash
curl -X PUT localhost:9101/internal/users/3f1c8b52-8f8e-4a3d-9f2e-0b7c1d9a4e11 \
  -H 'content-type: application/json' \
  -d '{"password": "new-secret"}'
```

```json
{
  "id": "3f1c8b52-8f8e-4a3d-9f2e-0b7c1d9a4e11",
  "username": "mark",
  "password": "new-secret"
}
```

| Status | When |
| --- | --- |
| `400` | An unknown field, or an empty string for a field that was sent |
| `404` | No user with that id |
| `409` | The new username is already taken |

---

### DELETE /internal/users/{id}

Delete an account. Frees the username for reuse.

```bash
curl -X DELETE localhost:9101/internal/users/3f1c8b52-8f8e-4a3d-9f2e-0b7c1d9a4e11
```

`204`, no body.

Idempotent: deleting a user that is already gone is also a `204`. The caller
asked for the row to not exist, and it does not.
