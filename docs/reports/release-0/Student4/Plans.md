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

- Create, list, view, update, deactivate, and delete activity and attraction
  catalogue entries.
- Classify catalogue entries under one or more controlled categories and filter
  them by text, location, category, price, duration, party suitability, age,
  accessibility, booking requirements, and date with an optional time-window.
- Record recurring weekly and one-off availability schedules, with validation
  that the complete activity duration fits within each available interval.
- Represent prices as exact AUD decimal values and distinguish per-person prices
  from flat admission charges.
- Resolve authoritative country and city information through the shared
  location service without joining across service databases.
- Add, reschedule, and remove activities from trips through the itinerary
  service, and expose committed activity costs for budget calculations.
- Provide advisory AI search planning and recommendations grounded in the
  current trip context and authoritative catalogue results.
