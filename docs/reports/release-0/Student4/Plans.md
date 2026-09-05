# Student 4 Plans

## Feature Plan

### Budget and Expense Management

This is an individual, forward-looking planning exercise recorded for Student
4. It neither reassigns the project's currently implemented Budget and Expense
Management service nor describes the Student 4 Activities and Attractions
service documented in the adjacent architecture and data-design folders.

This feature lets a traveller create a trip budget, record and categorise
expenses, and see the total budget, committed provider costs, actual spending,
and remaining budget in one place. It also includes advisory AI budget analysis
through the shared AI Mode service. AI output is read-only and requires human
review; it never persists a change directly.

The planned features are:

- Create, list, view, update, and delete trip budgets, with one budget per trip.
- Create, list, filter, view, update, and delete expenses.
- Categorise expenses as accommodation, transport, activities, food, shopping,
  or other, and filter them by trip, category, and date.
- Show total budget, committed costs, actual spending, and remaining budget
  using decimal-safe arithmetic.
- Combine committed costs from the transport, accommodation, and activities
  services.
- Keep budget and expense information current when the associated trip is
  updated.
- Provide advisory AI budget analysis grounded in the current summary.
