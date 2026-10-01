# Activity guides through shared RAG

The activity assistant panel has two modes. **Activity tools (MCP)** is the
existing shared-generation assistant described in
[the MCP assistant guide](mcp-assistant.md). **Activity guides (RAG)** answers
questions using only indexed TripGenie activity knowledge. Each answer shows
source citations and a confidence category, or a notice that there is not enough
context to answer.

```text
Browser ─▶ Student 4 frontend ─▶ Student 4 backend ─▶ host RAG :8011 ─▶ host AI-Mode :8006 ─▶ Ollama
           POST /suggestions/ask   POST /activity/knowledge   POST /query      /embed, /generate
           (mode=knowledge)        (feature fixed to student-4)
```

The frontend calls only its own backend. The backend fixes `feature: "student-4"`
and `top_k: 5`, and it maps the RAG contract into its own `KnowledgeResponse`
([backend API](backend-service-api.md#rag-activity-knowledge)). The RAG server
calculates confidence from retrieval scores and resolves citations from its
index, so Student 4 never trusts confidence or citation values written by the
model. Nothing is persisted.

## Knowledge sources

All sources are registered in
[`ai-services/rag-server/config/sources.json`](../../ai-services/rag-server/config/sources.json)
and tagged `student-4`. Student 4 queries also search the `shared` sources.

| Source ID | File | Answers questions about |
| --- | --- | --- |
| `activities-choosing-activities` | [choosing-activities.md](../../ai-services/rag-server/knowledge/activities/choosing-activities.md) | Category meanings, attractions versus guided experiences, timing, rainy days, families, groups |
| `activities-booking-and-pricing` | [booking-and-pricing.md](../../ai-services/rag-server/knowledge/activities/booking-and-pricing.md) | Per-person versus flat-admission totals, booking ahead, cancellations, minimum numbers |
| `activities-accessibility` | [accessibility-guide.md](../../ai-services/rag-server/knowledge/activities/accessibility-guide.md) | Confirmed versus unknown accessibility, wheelchair and step-free access, toilets, companion cards |
| `activities-safety-and-preparation` | [safety-and-preparation.md](../../ai-services/rag-server/knowledge/activities/safety-and-preparation.md) | What to bring, sun and heat, beaches, marine stingers, wildlife, bushwalking, age and health limits |
| `student-4-object-model` | [object-model.md](object-model.md) | Activity fields, invariants, pricing basis, nullable accessibility, availability |
| `student-4-backend-service-api` | [backend-service-api.md](backend-service-api.md) | Public routes, filters, errors and the itinerary integration |

The curated guides live next to Student 1's `knowledge/travel/` guides. Each
heading names its topic, and each section fits inside one 1,200-character chunk,
so a citation points to a single focused section. The feature documents are
indexed in place rather than copied, so they cannot drift. To add a source,
follow the [knowledge contribution rules](../../ai-services/rag-server/knowledge/README.md)
and rebuild the index.

`config/calibration-queries.json` includes Student 4 cases for pricing,
unknown accessibility, water-activity preparation, weather cancellation, and
one unrelated question that should return insufficient context.

## Local run

Start Ollama, AI-Mode and MCP with the
[local host services runbook](../../docs/reports/release-1/local-host-services-runbook.md).
RAG generation goes through AI-Mode `/generate`, which needs MCP. Use the
runbook's `llama3.1:8b` default for RAG. In local testing, `qwen2.5:7b` often
shortened citation IDs (for example `5:93e5f2e83e2f` instead of
`activities-booking-and-pricing:5:93e5f2e83e2f`). The shared server correctly
rejects those answers as `BAD_GATEWAY`, so Student 4 shows "failed to answer".
On an 8 GB GPU, start AI-Mode with `AI_MODE_CONTEXT_TOKENS=16384`. The
default of 32768 pushes much of `llama3.1:8b` onto the CPU. In local testing
that cut RAG answers from 40–120 seconds to 22–54 seconds, under the
120-second RAG timeout.
Then rebuild the index so that it includes the Student 4 sources, and serve
RAG:

```bash
cd ai-services/rag-server
uv run python -m rag_service ingest --rebuild
uv run python -m rag_service serve   # set RAG_BIND_HOST for native Linux Docker
```

From the repository root, verify the server, and then validate it in the
terminal without the UI:

```bash
curl -s http://127.0.0.1:8011/ready
curl -s -X POST http://127.0.0.1:8011/query -H 'Content-Type: application/json' \
  -d '{"query":"What should I bring on a snorkelling trip?","feature":"student-4","top_k":5,"correlation_id":"student4-rag-demo"}'
```

Start the application with
`docker compose --env-file shared/configuration/.env.example up --build -d`.
Compose sets `RAG_URL=http://host.docker.internal:8011` and
`RAG_ENABLED=true`. The backend route can be checked directly:

```bash
curl -s -X POST http://127.0.0.1:18008/activity/knowledge \
  -H 'Content-Type: application/json' \
  -d '{"question":"How is the total cost calculated for a per-person activity?"}'
```

## Functional checks

Open `http://localhost:8084`, select **Activity guides (RAG)** and ask:

- `What should I bring on a sunrise kayak or snorkelling trip?` should return
  a grounded answer that cites the safety and preparation guide.
- `How is the total cost worked out for four people on a per-person activity
  versus a flat-admission one?` should cite the booking and pricing guide or
  the object model.
- `Does unknown wheelchair access mean the activity is accessible?` should
  cite the accessibility guide.
- `Which laptop is best for learning to program?` should show the
  insufficient-context notice and no sources.

Stop RAG and ask again: the panel shows a safe error while browsing, CRUD and
the itinerary picker keep working.

## CI

`student-4-ci.yml` keeps the integration configured but sets
`STUDENT4_BACKEND_RAG_ENABLED=false` and `STUDENT4_AI_ASSISTANT_ENABLED=false`
for its Compose job. A verification step prints the effective backend
variables, checks that `/activity/knowledge` returns `status: "disabled"` and
that `/activity/assistant` reports that it is disabled, and checks that the
frontend renders the "Activity guides disabled" banner. Unit tests use injected
`httpx.MockTransport` fakes and never contact RAG, AI-Mode or Ollama.
