# Live cloud checks: screenshots and Students 2–5 CRUD (21 Oct 2026)

Captured from a developer machine against the public Azure frontends of the
deployment made by
[run 39580927565](https://github.com/YourNightmareIsOver/TripGenie/actions/runs/39580927565)
(image `188951a…`). These are manual checks by the report author, not
workflow output. Refs #171.

## Screenshots of the six public frontends

- **Tool:** headless Chrome 148 driven by Puppeteer.
- **Settings:** a fresh browser profile and a 1366×900 viewport. Each page
  waited for network idle and then 1.5 s more before the capture.
- **Captured:** 2026-10-21 11:12:44Z–11:12:58Z (22:12 AEDT).
- **Security:** no request used `http://`, and no request failed. Each page
  logged one console error for a 404 resource. `/favicon.ico` returns 404 on
  these apps, which is consistent with that error but was not confirmed as the
  only cause.
- **Screenshot content:** each one shows the first viewport of the landing
  page with no error banner or loading spinner.

| App | URL | HTTP | Page title | Screenshot |
| --- | --- | --- | --- | --- |
| Shared portal | <https://shared-ui.lemonrock-5a94d8cd.australiaeast.azurecontainerapps.io/> | 200 (17.6 s, cold start) | TripGenie | [shared-ui.png](screenshots/shared-ui.png) |
| Student 1 | <https://student-1-frontend.lemonrock-5a94d8cd.australiaeast.azurecontainerapps.io/> | 200 | Hobart Weekend Escape · TripGenie Student 1 | [student-1-frontend.png](screenshots/student-1-frontend.png) |
| Student 2 | <https://student-2-frontend.lemonrock-5a94d8cd.australiaeast.azurecontainerapps.io/> | 200 | Accommodation · TripGenie Student 2 | [student-2-frontend.png](screenshots/student-2-frontend.png) |
| Student 3 | <https://student-3-frontend.lemonrock-5a94d8cd.australiaeast.azurecontainerapps.io/> | 200 | Browse transport · TripGenie Student 3 | [student-3-frontend.png](screenshots/student-3-frontend.png) |
| Student 4 | <https://student-4-frontend.lemonrock-5a94d8cd.australiaeast.azurecontainerapps.io/> | 200 | Activities & Attractions · TripGenie Student 4 | [student-4-frontend.png](screenshots/student-4-frontend.png) |
| Student 5 | <https://student-5-frontend.lemonrock-5a94d8cd.australiaeast.azurecontainerapps.io/> | 200 | Budgets · TripGenie Student 5 | [student-5-frontend.png](screenshots/student-5-frontend.png) |

The portal cards show local Compose port labels (for example `:8081`), but
their links resolved to the HTTPS cloud URLs. The Student 2–5 pages still
*show* AI, RAG or MCP controls. Hiding those controls is not deployed; see the
report's [AI-off section](../cloud-deployment-report.md#ai-off-configuration).

## Students 2–5 CRUD through the cloud frontends

This was a scripted HTTP check against each frontend's existing form routes,
using the same requests the browser forms send. The check ran from 11:10:22Z
to 11:11:47Z.

- **Disposable data only.** Every record was a new disposable record named or
  tagged `CLOUD-EVIDENCE-20261021T111022Z`.
- **Cleanup.** Only those records were updated and deleted, and nothing
  existing was changed.
- **No AI routes.** No AI, RAG or MCP route was called.
- **Student 5 setup.** Student 5 needed a trip, so the check made a disposable
  Student 1 trip and deleted it at the end.

| Student | Create | Read | Update + read back | Delete | Verified gone |
| --- | --- | --- | --- | --- | --- |
| 2 Accommodation | `POST /accommodation` 200 "Added …" | Found by name (1 match), then `GET /accommodation/{id}` 200 | `PUT /accommodation/{id}` 200, new name shown | `DELETE /accommodation/{id}` 200 | Name search no longer returns the id |
| 3 Transport | `POST /options` 303 | `GET /options/{id}` 200 | `POST /options/{id}/edit` 303, new provider shown | `POST /options/{id}/delete` 303 | Detail page no longer shows it, and a provider filter shows "No transport options" |
| 4 Activities | `POST /manage/activity` 303 | `GET /activity/{id}` 200 | `POST /manage/activity/{id}` 303, new name shown | `POST /manage/activity/{id}/delete` 303 | Absent from detail and from `/manage`, which also lists inactive records |
| 5 Budgets | `POST /budgets` 303 (for the disposable trip) | `GET /budgets/{id}` 200 | `POST /budgets/{id}/edit` 303, new total shown | `POST /budgets/{id}/delete` 303 | Detail no longer shows it. The disposable Student 1 trip was deleted (303) and returned 404. |

All 28 checks passed. Notes:

- The frontends render not-found as an HTTP 200 page, so "gone" was confirmed
  from the content, not the status code.
- Student 5 expenses and Student 4 trip-itinerary links were not tested.
- These checks are point-in-time evidence. They are not a repeatable CI job:
  the cloud workflow's smoke test still automates CRUD for Student 1 only.
