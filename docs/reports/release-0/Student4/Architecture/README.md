# Student 4 Architecture

Student 4 owns TripGenie's Activities and Attractions catalogue. Its Release 0
implementation is split into three independently deployable Python services:
the traveller-facing frontend, the public backend/API, and an internal database
service that exclusively owns the Student 4 SQLite database.

The service-level architecture diagrams are documented separately:

- [Frontend architecture](frontend.md)
- [Backend/API architecture](backend-api.md)
- [Database architecture](database.md)

The diagrams show the deployed Docker Compose topology and the principal
runtime components. Ports `8008` and `8009` are exposed only on the Compose
network; only frontend port `8084` is published to the host by default.
