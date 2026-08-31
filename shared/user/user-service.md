← Back to [README.md](../../README.md)

# User Micro-Service

The user microservice owns accounts. It is the only service in TripGenie that
knows who anybody is:

1. Users can create an account
2. Users can sign in
3. Users can view their account, change their username or password, and delete it

It lives under `shared/` rather than a `student-N/` folder because accounts are
not one student's feature — every other service will eventually want to attach
its rows to a user.

The micro-service is comprised of three services:

1. The backend service
2. The database service
3. The frontend service

## Running It

From the repo root:

```bash
docker compose up --build shared-user
```

`shared-user` is a grouping entry, not a service — it exits immediately, and
the three services it depends on are the point. They keep running in the
background, so you get your prompt back. The pages are at
<http://localhost:9103> and the backend API at <http://localhost:9100>; the
database service stays on the compose network, unpublished.

Either end of the chain works if you want less than all three:

| Command | Starts |
| --- | --- |
| `docker compose up --build shared-user` | all three |
| `docker compose up --build shared-user-backend` | backend + database |
| `docker compose up --build shared-user-database` | database only |
| `docker compose logs -f shared-user-frontend` | follow one service's logs |
| `docker compose down` | stop them |

`--build` matters: without it compose reuses the image it built last time and
your code changes never make it into the container. The seeded accounts live in
the `shared-user-db` volume and survive a rebuild — `docker compose down -v` to
wipe them and re-seed.

Two accounts are seeded into an empty database so there is something to sign in
with: `mark` / `hunter2` and `ada` / `difference-engine`.

## A note on passwords

**Passwords are stored and compared in plaintext, on purpose.** So is the
absence of any session: signing in redirects to `/account/{id}` and that id in
the URL is the whole of "who is signed in".

This matches the posture the rest of the repo already documents — the compose
network is the trust boundary for Release 0, and no service does auth. It is
recorded here, in `models.py`, and on the backend's login route as `ponytail:`
comments naming the upgrade path (`hashlib.scrypt` into a `password_hash`
column, `hmac.compare_digest` to check it, and a signed cookie for the session)
so nobody mistakes it for an oversight.

Do not put a real password in it.

## Object Model

One table. That is the entire model, which is why there is no separate
`object-model.md`.

### User

| Field | Type | Notes |
| --- | --- | --- |
| `id` | UUID | Primary key, generated on insert. The only thing the frontend uses to identify a signed-in user. |
| `username` | string | `UNIQUE`. The login handle. A collision is what the API answers `409` to. |
| `password` | string | Plaintext, see above. Never leaves the backend service. |

The `UNIQUE` constraint is doing real work: it makes "that username is taken" a
database answer rather than a read-then-write race in application code. The
database service turns the resulting `IntegrityError` into the documented 409
in one handler that covers both `POST` and `PUT`.

## Backend Service

The public entry point. It is the only service permitted to call the database
service, and the only place the password comparison happens. Its own `User`
message has no password field at all, so a password cannot be echoed back to a
browser even by mistake.

It runs as the `shared-user-backend` container on port `9100`, published to the
host.

**API Documentation**: [backend-service-api.md](./docs/backend-service-api.md)

## Database Service

An HTTP wrapper around a SQLite database. Internal-only: it runs as the
`shared-user-database` container on port `9101`, `expose`d on the compose
network but never published, and the backend service is its sole caller.

**API Documentation**: [database-service-api.md](./docs/database-service-api.md)

## Frontend Service

The sign-in page and the account page. It talks to the backend service and
nothing else — it never reaches the database service.

It runs as the `shared-user-frontend` container on port `9103`, published to
the host.

**Documentation**: [frontend-service.md](./docs/frontend-service.md)

## Developing

From the repo root:

```bash
pip install -e "./shared/user[dev]"
ruff check shared/user && ruff format --check shared/user
pytest shared/user/tests -q
```

The three packages are named `database_service`, `backend_service` and
`frontend_service`, unprefixed, matching student 1 and student 2. That means
they collide at the import name with those students' packages — install one
student's service per virtualenv, which is what CI does.
