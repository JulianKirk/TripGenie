---
type: "query"
date: "2026-09-01T11:05:38.166405+00:00"
question: "How should one Activity model represent recurring available hours and fixed scheduled times?"
contributor: "graphify"
source_nodes: ["Activities and Attractions Management", "AvailabilityStatus", "duration_minutes()"]
---

# Q: How should one Activity model represent recurring available hours and fixed scheduled times?

## Answer

Expanded from graph vocabulary: activities, attractions, availability, booking, capacity, date, duration, time, window, departure. Use one Activity catalog entity. Flexible activities use recurring local-time availability windows plus date exceptions. Fixed-time activities use concrete scheduled sessions with timezone-aware start/end and optional capacity. Activity party-size limits are distinct from per-session remaining capacity. The availability mode selects which rules are valid and searchable.

## Source Nodes

- Activities and Attractions Management
- AvailabilityStatus
- duration_minutes()