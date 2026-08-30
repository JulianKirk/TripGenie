← Back to [README.md](../README.md)

# Accommodation Micro-Service

The accommodation microservice is responsible for all accommodation related business functions. A few are listed below:

1. Users can view accommodation details
2. Users can filter for accommodation based on properties such as price, type, location, etc.
3. Users can create bookings for specific accommodations
4. Users can rate accommodations

As such, the service has providence over the objects expanded on in [object-model.md](./docs/object-model.md).

The micro-service is comprised of three services:

1. The backend service
2. The database service
3. The frontend service

## Backend Service

This service is the main entry point for queries coming in from the frontend. 
This is responsible for managing data models in the accommodation database via the database service.
This service is integrated with Artificial Intelligence in order to provide accommodation suggestions from user queries.

**API Documentation**:

## Database Service

This service is essentially a wrapper for all database queries so that other services such as the backend service can manage data within the accommodation database with ease through HTTP requests on the wire.
This service is an internal service that is only exposed to the backend service for querying.

Built with FastAPI over the SQLAlchemy models in `database/database_service/`.
It runs as the `student-2-database` container on port `9001`, `expose`d on the
compose network but not published to the host. Start it with
`docker compose up student-2-database`.

**API Documentation**: [database-service-api.md](./docs/database-service-api.md)

## Frontend Service

The frontend service is built on HTMX that presents the accommodation details to the user via a webpage.
This service makes queries directly to the backend service and uses its response to display to the user.