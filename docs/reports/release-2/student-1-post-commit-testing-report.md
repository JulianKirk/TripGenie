# Student 1 Post-Commit CI/CD Testing Report

Release 2, criterion 4. Student 1 owns the Trip & Itinerary service. Its
workflow, `.github/workflows/student-1-ci.yml`, runs automated endpoint tests
for two backend functions after every push that touches `student-1/**`
(issue #174).

Workflow run: <link to be added after merge>

## Endpoints under test and why

| Endpoint | Function | Why it was chosen |
| --- | --- | --- |
| `POST /api/trips` | Create a trip | Trip CRUD is the core of the service. Every other feature (itinerary, accommodation, transport, activities, budgets) hangs off a trip id. |
| `POST /api/trips/{trip_id}/itinerary-items` | Add an itinerary item | This is the main itinerary-planning function. Students 2, 3 and 4 add items to a trip through it, and it enforces the trip's date window. |

## Test cases

File: `student-1/tests/endpoint/test_post_commit_endpoints.py`. The tests run
over HTTP against the live Compose stack (backend, plus a real SQLite database
container). Nothing is mocked. Each run uses unique `trip_ci_*` and `item_ci_*`
ids and deletes its trip afterwards. The delete cascades to the trip's items,
so reruns are idempotent.

| # | Endpoint | Test | Expected (observed) |
| --- | --- | --- | --- |
| 1 | `POST /trips` | `test_create_trip_returns_201_with_persisted_fields` | 201. Every sent field comes back, `days` covers the three trip dates, and `GET /trips/{id}` returns the trip with status 200. |
| 2 | `POST /trips` | `test_created_trip_is_listed` | 201, then the trip id appears in `GET /trips` (200). |
| 3 | `POST /trips` | `test_create_trip_rejects_end_before_start` | 422 `VALIDATION_ERROR` with detail field `start_date` ("must be on or before end_date"). Nothing is persisted: `GET` returns 404. |
| 4 | `POST /trips` | `test_create_trip_rejects_missing_name` | 422 `VALIDATION_ERROR` with detail `{"field":"name","issue":"Field required"}`. Nothing is persisted. |
| 5 | `POST /trips/{id}/itinerary-items` | `test_create_item_within_trip_returns_201_and_shows_on_day` | 201, the item is linked to the trip, and it is listed by `GET /trips/{id}/days/2027-03-02` (200). |
| 6 | `POST /trips/{id}/itinerary-items` | `test_create_item_for_unknown_trip_returns_404` | 404 `NOT_FOUND` ("Trip '...' was not found."). |
| 7 | `POST /trips/{id}/itinerary-items` | `test_create_item_outside_trip_dates_is_rejected` | 422 `VALIDATION_ERROR`, field `date`, "must fall between 2027-03-01 and 2027-03-03". The trip's item list stays empty. |

Errors use the service's standard envelope:
`{"error": {"code", "message", "details": [{"field", "issue"}]}}`.

## How it runs in `student-1-ci.yml`

The workflow triggers on `push` and `pull_request` for `student-1/**` (and its
own path). The `compose` job:

1. builds and starts `student-1-database`, `student-1-backend` and
   `student-1-frontend` with `docker compose up -d --build --no-deps`. RAG and
   MCP are disabled through `STUDENT1_BACKEND_RAG_ENABLED=false` and
   `STUDENT1_BACKEND_MCP_ENABLED=false`;
2. waits for the frontend's `/ready`, which depends on the backend and database;
3. **Post-commit endpoint tests**: from `student-1/`, runs
   `python -m pytest tests/endpoint --junitxml=student-1-endpoint-tests.xml -v`
   against `http://127.0.0.1:18001`. A failing test fails the job;
4. **Endpoint test summary** (`if: always()`): turns the JUnit XML into a
   pass/fail Markdown table. The table goes to the job summary
   (`$GITHUB_STEP_SUMMARY`) and to `student-1-endpoint-tests.md`;
5. **Upload endpoint test evidence** (`if: always()`): uploads the JUnit XML and
   the Markdown report as the artifact `student-1-endpoint-test-evidence`;
6. tears the stack down with `docker compose down -v`.

The tests skip when the backend is unreachable. `tests/endpoint` is also not in
the `testpaths` in `student-1/pyproject.toml`, so the unit-test jobs
(`pytest tests/backend`, and so on) never collect these tests.

## Local run

This run reproduced the CI job locally (Docker Desktop, project `s1endpoint`,
RAG/MCP disabled):

```text
$ STUDENT1_BACKEND_RAG_ENABLED=false STUDENT1_BACKEND_MCP_ENABLED=false \
    docker compose -p s1endpoint up -d --build --no-deps \
    student-1-database student-1-backend student-1-frontend
$ python scripts/ci/wait_for_http.py --label s1 --contains '"status":"ok"' http://127.0.0.1:8081/ready
PASS: s1 responded on attempt 2/8 after 2.05s (each request limited to 2s)
$ cd student-1 && python -m pytest tests/endpoint -rA
PASSED tests/endpoint/test_post_commit_endpoints.py::test_create_trip_returns_201_with_persisted_fields
PASSED tests/endpoint/test_post_commit_endpoints.py::test_created_trip_is_listed
PASSED tests/endpoint/test_post_commit_endpoints.py::test_create_trip_rejects_end_before_start
PASSED tests/endpoint/test_post_commit_endpoints.py::test_create_trip_rejects_missing_name
PASSED tests/endpoint/test_post_commit_endpoints.py::test_create_item_within_trip_returns_201_and_shows_on_day
PASSED tests/endpoint/test_post_commit_endpoints.py::test_create_item_for_unknown_trip_returns_404
PASSED tests/endpoint/test_post_commit_endpoints.py::test_create_item_outside_trip_dates_is_rejected
7 passed in 0.37s
$ docker compose -p s1endpoint down -v
```

A second run against the same stack also passed (7 passed). With the backend
unreachable (`STUDENT1_ENDPOINT_BASE_URL=http://127.0.0.1:1`), all 7 tests skip.

## Deliberate-failure demonstration

The `POST /trips` route in `student-1/backend/backend_service/app.py` was
broken on purpose, locally, to return the wrong success status:

```diff
-        status_code=status.HTTP_201_CREATED,
+        status_code=status.HTTP_200_OK,
```

After rebuilding only the backend, the suite failed with exit code 1:

```text
E       assert 200 == 201
ERROR tests/endpoint/test_post_commit_endpoints.py::test_create_trip_returns_201_with_persisted_fields
ERROR tests/endpoint/test_post_commit_endpoints.py::test_created_trip_is_listed
ERROR tests/endpoint/test_post_commit_endpoints.py::test_create_item_within_trip_returns_201_and_shows_on_day
ERROR tests/endpoint/test_post_commit_endpoints.py::test_create_item_outside_trip_dates_is_rejected
3 passed, 4 errors in 0.13s
```

In CI this fails the "Post-commit endpoint tests" step, and with it the
`compose` job. The change was then reverted (never committed), the backend was
rebuilt, and the suite passed again (7 passed).

An earlier attempt removed only the backend's item date-range check. The tests
still passed, because the database service enforces the same rule
(`repository.py`, "must fall between ...") and the backend passes its 422
through. That rule is checked in both layers, so the HTTP contract survives a
regression in either one.
