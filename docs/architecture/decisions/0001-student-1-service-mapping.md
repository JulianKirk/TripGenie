# ADR-0001: Map the Lab 04 three-service example onto TripGenie Student 1

## Status
Proposed

## Context

Lab 04 presents a three-service example using `frontend-service` on `8080`, `enrolment-service` on `5001`, and `database-service` on `5002`, with a static frontend, Python backend, and database service split. TripGenie already has a Group 07 shared home page on `8080` and a placeholder `student-1-service` entry on `8081` in `docker-compose.yml`. Student 1 therefore needs a documented mapping that preserves course intent without presenting the Lab 04 names or ports as mandatory course requirements.

## Decision

- Keep the Group 07 shared home page on host `8080`.
- Map the Lab 04 responsibility split onto three Student 1 runtime targets: `student-1-frontend`, `student-1-backend`, and `student-1-database`.
- Keep host `8081` as the Student 1 entry point from the shared home page.
- Treat backend port `8001` and database API port `8002` as **proposed** Student 1 internal ports chosen for project separation and to avoid collisions with other student-owned services.
- Keep the documentation framework-neutral at the contract level. The visible course example remains the closest reference pattern, but exact frontend/backend server-image choices stay implementation decisions until code exists.

## Consequences

- The docs can stay aligned with the visible three-service lab pattern while still matching Group 07 naming and navigation.
- Reviewers can distinguish the course example from the Student 1 project mapping.
- Any future implementation should update Docker Compose and CI to match the chosen mapping before the docs are promoted from proposed to implemented.
