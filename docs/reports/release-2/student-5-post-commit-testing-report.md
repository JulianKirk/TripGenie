# Student 5 Post-Commit CI/CD Testing Report

Workflow: `.github/workflows/student-5-ci.yml`  
Run: [Student 5 CI, run 39728255156](https://github.com/YourNightmareIsOver/TripGenie/actions/runs/39728255156/job/119657108299)  
Event: `push`  
Commit: `cde0075a77eb6b0baf7228a8cfd8bf0b27de2004`  
Job: `Build and Validate Student 5` — success  
Endpoint test step: success  
Artifact: `student-5-endpoint-test-evidence`  
Command: `python -m pytest tests/endpoint --junitxml=student-5-endpoint-tests.xml -v`  
Target: `http://127.0.0.1:18005`  
Result: **13 passed, 0 failed, 0 skipped**

## `POST /api/v1/expenses` — create expense

| Test | Result |
| --- | --- |
| `test_a_created_expense_is_stored_and_read_back` | PASS |
| `test_a_created_expense_is_listed_by_trip_and_category` | PASS |
| `test_an_invalid_expense_is_rejected[zero-amount]` | PASS |
| `test_an_invalid_expense_is_rejected[sub-cent-amount]` | PASS |
| `test_an_invalid_expense_is_rejected[unknown-category]` | PASS |
| `test_an_invalid_expense_is_rejected[currency]` | PASS |
| `test_an_invalid_expense_is_rejected[blank]` | PASS |
| `test_an_unknown_expense_is_not_found` | PASS |

Result: **8 passed**

## `GET /api/v1/budgets/{budget_id}/summary` — budget summary

| Test | Result |
| --- | --- |
| `test_the_summary_arithmetic_is_exact` | PASS |
| `test_the_summary_includes_a_new_expense_to_the_cent` | PASS |
| `test_the_summary_flags_an_unconverted_currency` | PASS |
| `test_an_unknown_budget_summary_is_not_found` | PASS |
| `test_a_malformed_budget_id_is_rejected` | PASS |

Result: **5 passed**