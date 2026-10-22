# Host service terminal validation: AI-Mode, RAG health and direct RAG queries

Captured 2026-10-02 (UTC), main `aec615c`, host services started per the [local host services runbook](../../local-host-services-runbook.md). The index path in RAG health/readiness is redacted.

## Health and readiness

```
$ curl -s http://127.0.0.1:8006/health
{"data":{"status":"ok","service":"ai-mode","dependencies":{"ollama":{"status":"ok","service":"ollama","detail":"Ollama responded successfully and the configured models are available.","code":null}}}}
$ curl -s http://127.0.0.1:8011/health
{"data":{"status":"ok","service":"rag-server","dependencies":{"ai_mode":{"status":"ok","service":"ai-mode","detail":"AI-Mode is ready.","code":null},"index":{"status":"ready","path":"<redacted-absolute-path>/rag.sqlite3","document_count":9,"chunk_count":124,"embedding_model":"nomic-embed-text","dimension":768,"detail":null}}}}
$ curl -s http://127.0.0.1:8011/ready
{"data":{"status":"ready","service":"rag-server","dependencies":{"ai_mode":{"status":"ok","service":"ai-mode","detail":"AI-Mode is ready.","code":null},"index":{"status":"ready","path":"<redacted-absolute-path>/rag.sqlite3","document_count":9,"chunk_count":124,"embedding_model":"nomic-embed-text","dimension":768,"detail":null}}}}
$ curl -s http://127.0.0.1:8012/health
{"status":"healthy","service":"tripgenie-mcp"}
```

## RAG index build (ingest)

Produced earlier on the same machine and commit by the runbook command `python -m rag_service ingest --rebuild` (run from `ai-services/rag-server`); summary output unedited:

```json
{
  "chunk_count": 124,
  "dimension": 768,
  "document_count": 9,
  "duration_ms": 3675,
  "embedded_chunk_count": 124,
  "embedding_model": "nomic-embed-text",
  "manifest_hash": "4561511db64b2cdeac1d6d368c5538b3f1468a436357ba9d0fdf26bd7fed9c2f",
  "reused_chunk_count": 0,
  "schema_version": "1"
}
```

Sources come from the allowlisted manifest [`config/sources.json`](../../../../../ai-services/rag-server/config/sources.json). Index files are generated locally and are not committed.

## Direct RAG queries (`POST http://127.0.0.1:8011/query`, `feature: "student-1"`, `top_k: 5`)

### "What are good day trips from Melbourne?"

```
$ curl -s -X POST http://127.0.0.1:8011/query -H 'content-type: application/json' -d '{"query":"What are good day trips from Melbourne?","feature":"student-1","top_k":5}'
{
    "data": {
        "schema_version": "1",
        "run_id": "rag_1476c0915d47",
        "correlation_id": "rag_1476c0915d47",
        "answer": "The Great Ocean Road and the Twelve Apostles, Phillip Island Penguin Parade, Yarra Valley wineries, and Puffing Billy steam railway in the Dandenong Ranges are good day trips from Melbourne.",
        "confidence_category": "high",
        "insufficient_context": false,
        "citations": [
            {
                "source_id": "travel-destination-guides",
                "path": "ai-services/rag-server/knowledge/travel/destination-guides.md",
                "title": "Destination Guides",
                "section": "Melbourne: getting around and day trips",
                "chunk_id": "travel-destination-guides:6:2779eb04ce78",
                "excerpt": "Melbourne: getting around and day trips Melbourne trams are free within the central Free Tram Zone; beyond it, trams, trains, and buses use the myki card or supported contactless payment. Popular day trips from Melbourne: - The Great Oce..."
            }
        ],
        "retrieval": {
            "requested_top_k": 5,
            "returned_chunks": 5,
            "maximum_score": 0.831892
        }
    }
}
[HTTP 200 time_total 73.056949s]
```

### "What is the live weather in Lisbon right now?"

```
$ curl -s -X POST http://127.0.0.1:8011/query -H 'content-type: application/json' -d '{"query":"What is the live weather in Lisbon right now?","feature":"student-1","top_k":5}'
{
    "data": {
        "schema_version": "1",
        "run_id": "rag_6758571fecca",
        "correlation_id": "rag_6758571fecca",
        "answer": "There is not enough indexed context to answer this question.",
        "confidence_category": "insufficient_context",
        "insufficient_context": true,
        "citations": [],
        "retrieval": {
            "requested_top_k": 5,
            "returned_chunks": 0,
            "maximum_score": 0.611496
        }
    }
}
[HTTP 200 time_total 51.322067s]
```

### "How do I bake sourdough bread?"

```
$ curl -s -X POST http://127.0.0.1:8011/query -H 'content-type: application/json' -d '{"query":"How do I bake sourdough bread?","feature":"student-1","top_k":5}'
{
    "data": {
        "schema_version": "1",
        "run_id": "rag_f06b6df61c0c",
        "correlation_id": "rag_f06b6df61c0c",
        "answer": "There is not enough indexed context to answer this question.",
        "confidence_category": "insufficient_context",
        "insufficient_context": true,
        "citations": [],
        "retrieval": {
            "requested_top_k": 5,
            "returned_chunks": 0,
            "maximum_score": 0.42848
        }
    }
}
[HTTP 200 time_total 1.078212s]
```

### Reading these results

Thresholds (defaults in `rag_service/config.py`): minimum relevance 0.5, medium 0.7, high 0.8.

| Query | Max score | Path taken | Result | Time |
| --- | --- | --- | --- | --- |
| Melbourne day trips | 0.832 | Retrieval above 0.8, grounded generation through AI-Mode, citation id validated against retrieved chunks | `high`, 1 citation (`travel-destination-guides`) | 73.1 s |
| Live weather in Lisbon | 0.611 | Above minimum, so generation ran; the model's grounded verdict was `insufficient_context` (climate text cannot answer a live-weather question), so the fixed response was returned | `insufficient_context`, no citations | 51.3 s (rerun 32.4 s) |
| Sourdough bread | 0.428 | Below minimum; generation skipped entirely | `insufficient_context`, no citations | 1.08 s (reruns 0.17 s, 0.07 s) |

Result: **Pass**. Both negative paths return the fixed insufficient-context answer with no citations and no unsupported generated text.
