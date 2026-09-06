# Understanding the Student 4 ERDs

An entity-relationship diagram (ERD) is a notation, not a separate level of
data design. Student 4 uses ER diagrams for both its logical and physical
models, with each diagram answering a different question.

| View | Question answered | Included | Deliberately omitted |
| --- | --- | --- | --- |
| [Conceptual model](conceptual.md) | What business concepts exist and how do they relate? | Domain concepts, ownership and cardinality | Attributes, keys, tables and storage types |
| [Logical ERD](logical.md) | What information must the domain retain? | Complete business attributes, logical types, primary and foreign keys, relationships and business cardinality | SQLite-specific types, indexes and compatibility structures |
| [Physical ERD](physical.md) | How is that information actually stored? | Exact tables, columns, SQLite storage types, nullability, cascades and the legacy alias table | API-only rules that SQLite cannot enforce by itself |

The logical and physical diagrams therefore contain more fields than a
high-level relationship overview would. They are the authoritative Student 4
ERDs; there is no separate partial ERD to keep synchronized.
