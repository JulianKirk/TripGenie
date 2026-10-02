# Student 1 backend/API: RAG, MCP and Release 0 AI suggestions

Captured 2026-10-02 (UTC) against the Compose `student-1-backend` (published at `127.0.0.1:18001`),
main `aec615c`. The backend reaches host RAG/MCP/AI-Mode through `host.docker.internal`.

## RAG grounded answer

Expected: `200`, an answer, a confidence category, and citations that map to indexed chunks.

```
$ curl -s -X POST http://127.0.0.1:18001/api/trips/trip_2026_melbourne_food_trail/rag-query -H 'content-type: application/json' -d '{"question":"What are good day trips from Melbourne?"}'
[HTTP 200 time_total 34.732077s]
```

```json
{
  "data": {
    "answer": "The Great Ocean Road and the Twelve Apostles, Phillip Island Penguin Parade, Yarra Valley wineries, and Puffing Billy steam railway in the Dandenong Ranges are popular day trips from Melbourne.",
    "confidence_category": "high",
    "insufficient_context": false,
    "citations": [
      {
        "source_id": "travel-destination-guides",
        "title": "Destination Guides",
        "section": "Melbourne: getting around and day trips",
        "path": "ai-services/rag-server/knowledge/travel/destination-guides.md",
        "chunk_id": "travel-destination-guides:6:2779eb04ce78",
        "excerpt": "Melbourne: getting around and day trips Melbourne trams are free within the central Free Tram Zone; beyond it, trams, trains, and buses use the myki card or supported contactless payment. Popular day trips from Melbourne: - The Great Oce..."
      }
    ],
    "retrieval": {
      "requested_top_k": 5,
      "returned_chunks": 5,
      "maximum_score": 0.831892
    },
    "run_id": "rag_75d644002453",
    "correlation_id": "student1-rag-2b482e551609",
    "trip_id": "trip_2026_melbourne_food_trail"
  }
}
```

## RAG insufficient context

Expected: `200`, `insufficient_context: true`, the fixed answer, no citations.

```
$ curl -s -X POST http://127.0.0.1:18001/api/trips/trip_2026_melbourne_food_trail/rag-query -H 'content-type: application/json' -d '{"question":"How do I bake sourdough bread?"}'
[HTTP 200 time_total 0.876196s]
```

```json
{
  "data": {
    "answer": "There is not enough indexed context to answer this question.",
    "confidence_category": "insufficient_context",
    "insufficient_context": true,
    "citations": [],
    "retrieval": {
      "requested_top_k": 5,
      "returned_chunks": 0,
      "maximum_score": 0.42848
    },
    "run_id": "rag_d5ce86b4bacd",
    "correlation_id": "student1-rag-739b7f026ee4",
    "trip_id": "trip_2026_melbourne_food_trail"
  }
}
```

## MCP options with a country

Expected: `200`, five read-only tools called through host MCP, structured results from Students 1-5 public APIs, `persisted: false`.

```
$ curl -s -X POST http://127.0.0.1:18001/api/trips/trip_2026_melbourne_food_trail/mcp-options -H 'content-type: application/json' -d '{"country":"Australia"}'
[HTTP 200 time_total 0.520068s]
```

`location`: `{"city": "Melbourne", "country": "Australia"}` · `persisted`: `false` · `summary`: `{"ok": 5, "error": 0, "skipped": 0}` · `correlation_id`: `student1-mcp-af4f352904c8`

| Tool | Arguments | Status | Result (summarised) |
|---|---|---|---|
| `trip_get_context` | `{"trip_id": "trip_2026_melbourne_food_trail"}` | ok | trip `trip_2026_melbourne_food_trail` (Melbourne, 2026-11-12–2026-11-16) |
| `accommodations_search` | `{"country": "Australia", "city": "Melbourne", "limit": 5}` | ok | 2 item(s): Fitzroy Terrace Guesthouse; Southbank Riverside Hotel |
| `activities_search` | `{"limit": 5, "filters": {"location": {"country": "Australia", "city": "Melbourne"}}}` | ok | 1 item(s): Melbourne museum discovery |
| `transport_search` | `{"destination": "Melbourne", "limit": 5}` | ok | 1 item(s): Qantas Sydney→Melbourne |
| `budgets_list` | `{"trip_id": "trip_2026_melbourne_food_trail", "limit": 5}` | ok | 1 budget(s): AUD 3000.00 |

## MCP options without a country (city-only destination)

Expected: `200`; the two location searches are reported as `skipped` with a reason, the other tools still run.

```
$ curl -s -X POST http://127.0.0.1:18001/api/trips/trip_2026_melbourne_food_trail/mcp-options -H 'content-type: application/json' -d '{}'
[HTTP 200 time_total 0.033314s]
```

`location`: `{"city": "Melbourne", "country": null}` · `persisted`: `false` · `summary`: `{"ok": 3, "error": 0, "skipped": 2}` · `correlation_id`: `student1-mcp-8f8e0fc3c8f5`

| Tool | Arguments | Status | Result (summarised) |
|---|---|---|---|
| `trip_get_context` | `{"trip_id": "trip_2026_melbourne_food_trail"}` | ok | trip `trip_2026_melbourne_food_trail` (Melbourne, 2026-11-12–2026-11-16) |
| `accommodations_search` | `{"country": null, "city": "Melbourne", "limit": 5}` | skipped | country is required for a location search; use a 'City, Country' destination or send a country |
| `activities_search` | `{"limit": 5, "filters": {"location": {"country": null, "city": "Melbourne"}}}` | skipped | country is required for a location search; use a 'City, Country' destination or send a country |
| `transport_search` | `{"destination": "Melbourne", "limit": 5}` | ok | 1 item(s): Qantas Sydney→Melbourne |
| `budgets_list` | `{"trip_id": "trip_2026_melbourne_food_trail", "limit": 5}` | ok | 1 budget(s): AUD 3000.00 |

## Release 0 AI suggestions (AI-Mode, llama3.1:8b)

Expected: `200`, draft suggestions from AI-Mode with `persisted: false`; nothing is saved until the user reviews and saves through CRUD.

```
$ curl -s -X POST http://127.0.0.1:18001/api/trips/trip_2026_melbourne_food_trail/ai-suggestions -H 'content-type: application/json' -d '{"requested_date":"2026-11-13","goal":"Plan a relaxed food-focused day","interests":"food, markets"}'
[HTTP 200 time_total 78.953865s]
```

```json
{
  "trip_id": "trip_2026_melbourne_food_trail",
  "requested_date": "2026-11-13",
  "model": "llama3.1:8b",
  "prompt_asset": "runtime_ai_suggestions_v2.md",
  "run_id": "aimode_48abc979ccd6",
  "correlation_id": "ai_5ef92bfee23c",
  "attempt_count": 1,
  "persisted": false,
  "approval_required": true,
  "suggestions (fields summarised)": [
    {
      "title": "Food Court",
      "date": "2026-11-13",
      "start_time": null,
      "end_time": null,
      "category": "activity",
      "location": null
    },
    {
      "title": "Queen Victoria Market Tour",
      "date": "2026-11-13",
      "start_time": null,
      "end_time": null,
      "category": "activity",
      "location": null
    }
  ]
}
```

## Result

| Request | HTTP | Time | Status |
| --- | --- | --- | --- |
| `rag-query` grounded | 200 | 34.7 s | Pass: `high`, 1 validated citation |
| `rag-query` insufficient | 200 | 0.88 s | Pass: generation skipped, no citations |
| `mcp-options` with country | 200 | 0.52 s | Pass: 5 ok, `persisted: false` |
| `mcp-options` without country | 200 | 0.03 s | Pass: 3 ok, 2 skipped with reason |
| `ai-suggestions` | 200 | 79.0 s | Pass (functional): 2 drafts, `persisted: false`, `approval_required: true` |

Observation, not hidden: the AI suggestion drafts from `llama3.1:8b` were
sparse (no times, locations or rationale, and "Food Court" categorised as an
activity). The contract held; quality depends on the local model, and the
user must review each draft before it is saved through CRUD.
