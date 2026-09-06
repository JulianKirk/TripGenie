# Student 4 Plans

## Feature Plan

### Activities and Attractions Management

This feature lets a traveller browse, search, and filter activities and
attractions, inspect their prices and availability, and add suitable activities
to a trip. It also lets catalogue managers maintain activity details,
categories, locations, accessibility information, booking guidance, and
schedules. Advisory AI recommendations are provided through the shared AI Mode
service. AI output is read-only and requires human review; it never persists a
change directly.

The planned features are:

- Create, list, view, update, deactivate, and delete activities and attractions.
- Categorise, search, and filter activities by location, price, availability,
  suitability, accessibility, and booking requirements.
- Store a variety of activities with different weekly and one-off schedules.
- Support per-person and flat admission pricing with decimal-safe arithmetic.
- Add, reschedule, and remove activities from trips, and provide committed
  activity costs to the budget service.
- Provide advisory AI recommendations grounded in current trip and catalogue
  data.

## Risk Management Plan (Individual)

<!-- markdownlint-disable MD013 -->

| Risk | Mitigation Strategy |
| --- | --- |
| Invalid schedules show activities at the wrong time. | Validate weekly and one-off schedules, ordered times, and activity duration before saving. |
| Deleting an activity leaves a stale trip reference. | Check itinerary references before deletion; deactivate the activity when it is still in use. |
| Location or itinerary services are unavailable. | Report dependency failures clearly and keep service data isolated so an outage cannot corrupt the activity catalogue. |
| A cross-service API change breaks activity requests. | Validate responses against independent schemas and use contract tests to detect incompatible changes. |
| AI Mode is unavailable or recommends an unknown activity. | Keep catalogue operations independent of AI, reject ungrounded results, and never let AI persist changes directly. |

<!-- markdownlint-enable MD013 -->
