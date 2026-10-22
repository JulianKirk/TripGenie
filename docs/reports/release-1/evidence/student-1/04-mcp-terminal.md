# MCP server terminal validation

Captured 2026-10-02 (UTC) on main `aec615c`. Host MCP server at `127.0.0.1:8012/mcp`,
started per the [local host services runbook](../../local-host-services-runbook.md). Commands
run from `ai-services/mcp-server` with the host virtual environment. Long payloads are
summarised (counts, ids, first item); values are otherwise unedited.

## Health

```
$ curl -s http://127.0.0.1:8012/health
{"status":"healthy","service":"tripgenie-mcp"}
```

## Registered tools (`python -m tripgenie_mcp inspect`, 0.69s)

Expected: every catalogue tool registered with an explicit input schema and annotations. Actual: 19 tools.

| Tool | readOnlyHint | destructiveHint | Inputs | Called by Student 1 backend |
|---|---|---|---|---|
| `trip_get_context` | True | False | trip_id | yes |
| `trips_list_itinerary_items` | True | False | limit, trip_id | no |
| `accommodations_search` | True | False | city, country, limit | yes |
| `accommodations_get` | True | False | accommodation_id | no |
| `accommodations_committed_costs` | True | False | trip_id | no |
| `transport_search` | True | False | destination, limit, origin | yes |
| `transport_get` | True | False | transport_id | no |
| `transport_compare` | True | False | ids | no |
| `transport_trip_costs` | True | False | trip_id | no |
| `activities_search` | True | False | filters, limit, offset, text | yes |
| `activities_create` | False | False | activity | no |
| `activities_update` | False | True | activity, activity_id | no |
| `activities_delete` | False | True | activity_id, confirm | no |
| `activities_get` | True | False | activity_id | no |
| `activities_list_categories` | True | False | none | no |
| `activities_committed_costs` | True | False | trip_id | no |
| `budgets_list` | True | False | limit, trip_id | yes |
| `budgets_get_summary` | True | False | budget_id | no |
| `expenses_list` | True | False | category, date_from, date_to, limit, trip_id | no |

Every input schema has `additionalProperties: false`: True. The three non-read-only tools belong to Student 4's activity catalogue; the Student 1 backend calls only the five read-only tools marked yes.

## Tool call: trip_get_context (Student 1 public API)

```
$ python -m tripgenie_mcp call trip_get_context '{"trip_id":"trip_2026_melbourne_food_trail"}'
```

Wall time: 1.78s. `isError`: False.

```json
{
  "ok": true,
  "correlation_id": "mcp-695cd8d690f0",
  "source": "student-1",
  "data (summarised)": {
    "id": "trip_2026_melbourne_food_trail",
    "name": "Melbourne Food Trail",
    "destination": "Melbourne",
    "start_date": "2026-11-12",
    "end_date": "2026-11-16",
    "status": "draft",
    "days": 5,
    "itinerary_items": 1,
    "accommodations": 0,
    "activities": 0
  }
}
```

## Tool call: activities_search (Student 4 public API)

```
$ python -m tripgenie_mcp call activities_search '{"limit":3,"filters":{"location":{"country":"Australia","city":"Melbourne"}}}'
```

Wall time: 2.19s. `isError`: False.

```json
{
  "ok": true,
  "correlation_id": "mcp-b68224c08b50",
  "source": "student-4",
  "data (summarised)": {
    "count": 1,
    "truncated": false,
    "first_item": {
      "id": "165586ae-9c09-5839-bae2-507a8074186f",
      "name": "Melbourne museum discovery",
      "price": "30.00",
      "categories": [
        "CULTURE",
        "FAMILY"
      ]
    }
  }
}
```

## Tool call: transport_search (Student 3 public API)

```
$ python -m tripgenie_mcp call transport_search '{"destination":"Melbourne","limit":3}'
```

Wall time: 0.74s. `isError`: False.

```json
{
  "ok": true,
  "correlation_id": "mcp-725e57416507",
  "source": "student-3",
  "data (summarised)": {
    "count": 1,
    "truncated": false,
    "first_item": {
      "id": "transport_2026_qf436_syd_mel",
      "provider": "Qantas",
      "origin": "Sydney",
      "destination": "Melbourne",
      "price": "205.50"
    }
  }
}
```

## Boundary checks

Expected: an unregistered tool and unexpected arguments are rejected before any provider call.

## Unregistered tool is rejected

```
$ python -m tripgenie_mcp call trip_delete '{"trip_id":"x"}'
```

Wall time: 0.90s. `isError`: True.

```
Unknown tool: trip_delete
```

## Unexpected arguments are rejected

```
$ python -m tripgenie_mcp call activities_search '{"country":"Australia","city":"Melbourne","limit":3,"unexpected":1}'
```

Wall time: 0.96s. `isError`: True.

```
Error executing tool activities_search: 3 validation errors for activities_searchArguments
country
Extra inputs are not permitted [type=extra_forbidden, input_value='Australia', input_type=str]
city
Extra inputs are not permitted [type=extra_forbidden, input_value='Melbourne', input_type=str]
unexpected
Extra inputs are not permitted [type=extra_forbidden, input_value=1, input_type=int]
```

Result: **Pass**. Read-only tools returned structured `ok`/`data`/`source`/`correlation_id` results from the owning feature's public API; the unregistered tool and extra arguments were rejected by the server schema.
