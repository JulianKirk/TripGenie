# Student 4 Data Design

Student 4 owns TripGenie's Activities and Attractions catalogue. The service
stores activity aggregates in its own SQLite database and exposes them through
the Student 4 database and backend APIs. Country and city records remain owned
by the shared reference service; Student 4 stores their UUIDs but does not join
across service databases.

The Release 0 data design is documented at three levels:

- [Conceptual data design](conceptual.md) ([PNG](conceptual.png))
- [Logical data model (ERD)](logical.md) ([PNG](logical.png))
- [Physical database model (ERD)](physical.md) ([PNG](physical.png))

The [ERD guide](erd.md) explains how the logical and physical diagrams relate
and why they intentionally show different levels of detail.

This release models catalogue and planning data only. Booking transactions,
ticket inventory and images are outside Student 4's persistence scope;
`booking_required` and `booking_notes` provide planning guidance rather than
representing a reservation made through TripGenie.
