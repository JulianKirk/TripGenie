← Back to [user-service.md](../user-service.md)

### Table of Contents

- [Service Endpoints](#service-endpoints)
  - [GET /health](#get-health)
- [User Endpoints](#user-endpoints)
  - [POST /users](#post-users)
  - [POST /users/login](#post-userslogin)
  - [GET /users/{id}](#get-usersid)
  - [PUT /users/{id}](#put-usersid)
  - [DELETE /users/{id}](#delete-usersid)

# User Backend Service API

## Service Scope

This service runs on `http://shared-user-backend:9100`, published to the host.
It is the public face of the user micro-service: the sign-in pages call it, and
so can the other students' backend services. It is in turn the only caller of
the user database service.

```
frontend ──► backend (you are here) ──► database ──► SQLite
```

ponytail: no auth on this API. The compose network is the trust boundary for
Release 0, the same as every other service in the repo. Which is worth stating
plainly given what this service does: **anyone who can reach port 9100 can read
any account's username by id, change any password, and delete any account.**
There is no check that the caller is the user they are acting on. That check
arrives with sessions.

### The password never comes back out

The database service stores and returns passwords in plaintext. This service's
copy of the user message **has no password field at all**, so every response
here is filtered through a model that cannot carry one:

```python
class User(BaseModel):
    model_config = ConfigDict(extra="ignore")  # this is what drops it
    id: UUID | None = None
    username: str | None = None
```

A password goes in on a create, a login or an update, and never comes back.
There is an e2e test asserting exactly that across a whole account lifecycle.

### Running it

```bash
docker compose up shared-user-backend
```

That starts the database service behind it too. To run the image alone:

```bash
docker build -f shared/user/backend/Dockerfile -t shared-user-backend shared/user
docker run --rm -p 9100:9100 shared-user-backend
```

With no database service reachable, `/health` answers `degraded` with a `200`
and every other endpoint answers `503`.

### Configuration

| Variable       | Default                             | Purpose                                  |
|----------------|-------------------------------------|------------------------------------------|
| `DATABASE_URL` | `http://shared-user-database:9101`  | The database **service**, not a DSN      |
| `DB_TIMEOUT`   | `5`                                 | Seconds before a call to it is a `503`   |

`DATABASE_URL` means something different here than it does in the database
service, which uses the same name for its SQLite path. The two containers must
not share an env file.

### Errors

| Status | When |
| --- | --- |
| `400` | Invalid input: a missing required field, an empty string, an unknown field |
| `401` | Sign-in failed |
| `404` | No user with that id |
| `409` | The username is already taken |
| `502` | The database service answered, but not usably |
| `503` | The database service could not be reached, or timed out |

Error bodies are `{"detail": ...}`.

`400`, `404` and `409` are the database service's own answers, passed through
unchanged — it is the service that can answer them correctly. `502` and `503`
are this service reporting that it could not reach its data; the mapping lives
in one function in `client.py`, so every upstream call fails the same way.

---

## Service Endpoints

### GET /health

Liveness, and the state of the database service behind this one — so a caller
can tell "the backend is down" from "the backend is up but its data is not".
Always `200`.

```bash
curl localhost:9100/health
```

```json
{ "status": "ok", "service": "shared-user-backend", "database": "ok" }
```

When the database service is unreachable:

```json
{ "status": "degraded", "service": "shared-user-backend", "database": "unreachable" }
```

---

## User Endpoints

### POST /users

Sign up.

```bash
curl -X POST localhost:9100/users \
  -H 'content-type: application/json' \
  -d '{"username": "mark", "password": "hunter2"}'
```

`201`:

```json
{ "id": "3f1c8b52-8f8e-4a3d-9f2e-0b7c1d9a4e11", "username": "mark" }
```

| Status | When |
| --- | --- |
| `400` | Missing or empty `username`/`password`, or an unknown field |
| `409` | `{"detail": "username already taken"}` |

---

### POST /users/login

Who this is, if the password matches. This is the only endpoint with logic of
its own: it looks the username up on the database service and compares the
password here.

```bash
curl -X POST localhost:9100/users/login \
  -H 'content-type: application/json' \
  -d '{"username": "mark", "password": "hunter2"}'
```

`200`:

```json
{ "id": "3f1c8b52-8f8e-4a3d-9f2e-0b7c1d9a4e11", "username": "mark" }
```

**The id in that response is the whole of "signed in".** There is no token, no
cookie and no session; the frontend puts the id in the URL and whoever holds
that URL is that user. See the note in [user-service.md](../user-service.md).

| Status | When |
| --- | --- |
| `400` | Missing or empty `username`/`password` |
| `401` | `{"detail": "invalid username or password"}` |

A wrong password and an unknown username give **the same** `401` with the same
body, so the endpoint cannot be used to find out which usernames exist.

---

### GET /users/{id}

One account. No password — there is no shape in which this service returns one.

```bash
curl localhost:9100/users/3f1c8b52-8f8e-4a3d-9f2e-0b7c1d9a4e11
```

```json
{ "id": "3f1c8b52-8f8e-4a3d-9f2e-0b7c1d9a4e11", "username": "mark" }
```

| Status | When |
| --- | --- |
| `404` | `{"detail": "user not found"}` |

---

### PUT /users/{id}

Change the username, the password, or both. Both fields are optional; whatever
is sent is what changes, and an omitted field is left alone.

```bash
curl -X PUT localhost:9100/users/3f1c8b52-8f8e-4a3d-9f2e-0b7c1d9a4e11 \
  -H 'content-type: application/json' \
  -d '{"password": "new-secret"}'
```

```json
{ "id": "3f1c8b52-8f8e-4a3d-9f2e-0b7c1d9a4e11", "username": "mark" }
```

An explicit `null` is dropped rather than forwarded — the database service
forbids unknown fields and would otherwise be asked to set one to null.

| Status | When |
| --- | --- |
| `400` | An unknown field, or an empty string for a field that was sent |
| `404` | No user with that id |
| `409` | The new username is already taken |

---

### DELETE /users/{id}

Delete an account. Frees the username for reuse.

```bash
curl -X DELETE localhost:9100/users/3f1c8b52-8f8e-4a3d-9f2e-0b7c1d9a4e11
```

`204`, no body. Idempotent — deleting an account that is already gone is also a
`204`.
