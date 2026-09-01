---
type: "query"
date: "2026-09-01T11:27:13.164351+00:00"
question: "Can Activity use one-to-many ActivityAvailabilitySchedule rows with recurring weekly or one-off dates?"
contributor: "graphify"
source_nodes: ["AvailabilityStatus", "duration_minutes()"]
---

# Q: Can Activity use one-to-many ActivityAvailabilitySchedule rows with recurring weekly or one-off dates?

## Answer

Expanded from graph vocabulary: availability, date, time, window, duration, arrival, departure. Yes. ActivityAvailabilitySchedule should carry activity_id, schedule_kind, recurring_weekly, weekday or date, start_time, and end_time. Validation requires weekday only for recurring rows and date only for one-off rows. Multiple rows represent multiple weekly windows or fixed sessions. schedule_kind must distinguish an open availability window from a fixed session because identical time columns otherwise have ambiguous meaning.

## Source Nodes

- AvailabilityStatus
- duration_minutes()