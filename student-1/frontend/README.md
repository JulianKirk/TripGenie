# Student 1 frontend service

This FastAPI + Jinja + HTMX frontend renders TripGenie's Trip & Itinerary Management UI and talks to the Student 1 backend over HTTP only.

## Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `STUDENT1_FRONTEND_BACKEND_BASE_URL` | `http://student-1-backend:8001` | Base URL for the Student 1 backend service. |
| `STUDENT1_FRONTEND_BACKEND_API_PREFIX` | `/api` | Backend public API prefix used for CRUD requests. |
| `STUDENT1_FRONTEND_BACKEND_TIMEOUT_SECONDS` | `5` | Timeout for frontend-to-backend HTTP calls. |
| `STUDENT1_FRONTEND_SERVICE_NAME` | `student-1-frontend` | Service name reported by frontend health endpoints. |
| `STUDENT1_FRONTEND_ACCOMMODATION_UI_URL` | `http://localhost:9003` | Where a **browser** reaches student 2's webpage. A row in the Accommodation section links there, so this is the address on the user's machine, not the compose hostname this container would use. |

## Runtime notes

- The UI keeps **UI mode** and **AI mode** visually distinct. Issue #12 replaces the disabled placeholder with an accessible AI suggestion form and HTMX result states.
- Form submissions preserve entered values and show backend field/general errors for both normal page loads and HTMX swaps.
- AI results are always labelled as drafts and route users into the normal itinerary-item create form for review/edit/save. There is no silent bulk persistence path.
- AI-mode preserves entered values on backend/model validation failures and keeps CRUD usable when the shared AI-Mode dependency is unavailable.
- The trip page has an **Accommodation** section listing what is booked for that trip: name, the check-in and check-out (with times when recorded), and what the stay costs. The name and price come from student 2 by way of this service's backend, and are shown as the accommodation id and a dash when that service cannot be reached.
- Clicking a row opens that accommodation on student 2's own page (`/?accommodation=<id>`), because that is the service that owns it. The bin on each row goes to the same confirmation screen pattern as deleting an itinerary item — it removes the accommodation from the trip, not the accommodation itself.
- `GET /health` reports frontend health plus backend dependency status. `GET /ready` returns `503` until the backend dependency is ready. These operational endpoints are TripGenie service decisions for Release 0.
