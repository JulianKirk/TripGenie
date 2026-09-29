# Student 5 Budget and Expense Rules

This document states the rules the Student 5 Budget and Expense Management
service enforces today. It is a curated knowledge source for the shared RAG
server. Every rule below is implemented in the Student 5 backend or database
service; nothing here is aspirational.

## Purpose and ownership

Student 5 owns trip budgets, recorded expenses, budget summaries, and advisory
budget analysis. It does not own trips, transport, accommodation, or
activities. Trip details come from the Student 1 trips API. Committed costs come
from the public transport (Student 3), accommodation (Student 2), and activities
(Student 4) APIs. Student 5 never reads another service's database.

## One budget per trip

A trip has at most one budget. Creating a second budget for the same `trip_id`
is rejected with a conflict. A trip can have many expenses. Deleting a budget
does not delete the trip's expense history, because budgets and expenses have
independent lifecycles.

## Budget allocations

A budget has a total and five category allocations: accommodation, transport,
activities, food, and other. Each allocation is zero or more. The sum of the
five allocations must not exceed the total budget; a request that exceeds it is
rejected with a validation error. Allocations are planning figures only and do
not change the remaining budget calculation.

## Expense categories

Every expense uses exactly one category: `accommodation`, `transport`,
`activities`, `food`, `shopping`, or `other`. An expense amount must be greater
than zero. When the Student 1 trips API is reachable, a budget or expense for a
trip it reports as missing is rejected, and an expense date must fall within
the trip's start and end dates. If the trips API is unreachable, the record is
still accepted so budgeting keeps working.

## Money representation

All money is exact decimal. Amounts are stored and exchanged as two-decimal
strings such as `"1250.00"`, and are processed with Python `Decimal`, never
binary floating point. Budget totals, allocations, and expense amounts must be
between 0 and 1,000,000,000.00. Currencies are three uppercase ISO 4217 letters,
for example `AUD`.

## Actual spending

Actual spending is the sum of recorded expenses for the budget's trip that use
the budget's currency. Category totals break actual spending down by expense
category. `actual_spending_complete` is false when any expense uses another
currency; those expenses are counted in `unconverted_expense_count` and are not
added to actual spending.

## Committed costs

Committed costs are the sum of provider subtotals that are available and use
the budget's currency. The providers are transport, accommodation, and
activities. `committed_costs_complete` is false when any provider is not
available, returns a different currency, or has no subtotal.

## Remaining budget

The remaining budget is calculated, never stored or edited:

`remaining_budget = total_budget - actual_spending - committed_costs`

The remaining budget may be negative when spending and commitments exceed the
total. `remaining_budget_complete` is true only when both actual spending and
committed costs are complete. When it is false, the user interface marks the
affected totals with an asterisk.

## Provider availability states

Each provider in a budget summary has one status:

- `available`: the provider answered in the budget currency, and its subtotal is
  included in committed costs.
- `unavailable`: the provider could not be reached, timed out, returned an HTTP
  error, or used a currency that cannot be converted. Its cost is not included.
- `invalid_response`: the provider answered, but the response did not match its
  contract. Its cost is not included.

An unavailable or invalid provider cost is never treated as zero. The summary is
marked incomplete instead, so a missing cost cannot make the remaining budget
look healthier than it is.

## Currency policy

Student 5 does not convert currencies. Expenses and provider costs in a
currency other than the budget currency are excluded from totals and reported
as incomplete. Live exchange rates are not used.

## AI budget analysis is advisory

The budget analysis feature sends the selected budget's summary and expenses to
the shared AI-Mode service. The model's answer is advisory. Deterministic totals
calculated by the backend remain authoritative. An answer that does not quote
the budget currency and at least one exact budget amount is rejected after one
retry.

## MCP budget tools are read-only

Student 5 contributes three read-only tools to the shared MCP server:
`budgets_list`, `budgets_get_summary`, and `expenses_list`. They call only the
Student 5 public API with GET requests, return at most 50 items, keep money as
exact strings, and omit expense notes and payment methods. No MCP tool creates,
changes, or deletes a budget or expense.

## What the budget assistant cannot answer

The budget knowledge assistant answers only from indexed TripGenie
documentation. It cannot provide live exchange rates, booking availability,
prices from external websites, personal expense details, or another student's
private data. Such questions return an insufficient-context response.
