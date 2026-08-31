# Student 1 frontend service

This FastAPI + Jinja + HTMX frontend renders TripGenie's Trip & Itinerary Management UI and talks to the Student 1 backend over HTTP only.

## Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `STUDENT1_FRONTEND_BACKEND_BASE_URL` | `http://student-1-backend:8001` | Base URL for the Student 1 backend service. |
| `STUDENT1_FRONTEND_BACKEND_API_PREFIX` | `/api` | Backend public API prefix used for CRUD requests. |
| `STUDENT1_FRONTEND_BACKEND_TIMEOUT_SECONDS` | `5` | Timeout for frontend-to-backend HTTP calls. |
| `STUDENT1_FRONTEND_SERVICE_NAME` | `student-1-frontend` | Service name reported by frontend health endpoints. |

## Runtime notes

- The UI keeps **UI mode** and **AI mode** visually distinct. Issue #11 ships a disabled AI suggestion affordance only; live itinerary suggestions stay deferred to issue #12.
- Form submissions preserve entered values and show backend field/general errors for both normal page loads and HTMX swaps.
- `GET /health` reports frontend health plus backend dependency status. `GET /ready` returns `503` until the backend dependency is ready. These operational endpoints are TripGenie service decisions for Release 0.
