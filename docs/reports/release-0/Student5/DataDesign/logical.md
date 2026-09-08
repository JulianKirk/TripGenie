# Student 5 Logical Data Model (ERD)

Budgets retain one total spending limit plus five non-negative planned
allocations. Expenses retain positive actual amounts classified independently;
`shopping` is an expense category but does not have a dedicated budget
allocation field. Money has at most two decimal places and all records carry a
three-letter uppercase currency code.

This implementation-neutral ERD shows every business attribute, logical data
type, identifier and relationship, but not SQLite storage details or indexes.
A high-resolution [PNG export](logical.png) is included alongside this
document.

```mermaid
%%{init: {"theme":"base","themeVariables":{"fontFamily":"Inter, ui-sans-serif, system-ui, sans-serif","primaryColor":"#eff6ff","primaryTextColor":"#0f172a","primaryBorderColor":"#2563eb","lineColor":"#475569","tertiaryColor":"#f8fafc"}}}%%
erDiagram
    TRIP ||..o| BUDGET : "has external reference"
    TRIP ||..o{ EXPENSE : "has external reference"

    TRIP {
        string trip_id PK "externally owned by Student 1"
    }

    BUDGET {
        UUID budget_id PK
        string trip_id UK "external reference; not a database FK"
        string currency "three uppercase letters"
        decimal total_budget "non-negative; two decimal places"
        decimal accommodation_budget "non-negative; default 0.00"
        decimal transport_budget "non-negative; default 0.00"
        decimal activities_budget "non-negative; default 0.00"
        decimal food_budget "non-negative; default 0.00"
        decimal other_budget "non-negative; default 0.00"
        datetime created_at "UTC"
        datetime updated_at "UTC"
    }

    EXPENSE {
        UUID expense_id PK
        string trip_id "external reference; not a database FK"
        ExpenseCategory category "six controlled values"
        string description
        decimal amount "positive; two decimal places"
        string currency "three uppercase letters"
        date date
        string payment_method "optional"
        string notes "optional"
        datetime created_at "UTC"
        datetime updated_at "UTC"
    }
```

The principal logical rules are: a trip has at most one budget; each category
allocation and the total budget are non-negative; the five allocations
together cannot exceed the total; and every expense amount is positive.
Expense categories are `accommodation`, `transport`, `activities`, `food`,
`shopping` and `other`. Budget and expense deletion remain independent.