# Student 4 Data Design

Student 4 owns TripGenie's Activities and Attractions catalogue. The service
stores activity aggregates in its own SQLite database and exposes them through
the Student 4 database and backend APIs. Country and city records remain owned
by the shared reference service; Student 4 stores their UUIDs but does not join
across service databases.

The Release 0 data design is documented at four levels:

- [Conceptual data design](conceptual.md)
- [Entity-relationship diagram (ERD)](erd.md)
- [Logical data design](logical.md)
- [Physical data design](physical.md)

The diagrams reflect the implementation in `student-4/database` while leaving
the existing working documentation under `student-4/docs` unchanged.
