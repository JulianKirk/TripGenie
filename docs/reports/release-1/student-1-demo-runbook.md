# Student 1 Release 1 demo runbook

Segment: about **2 minutes** of the group's 10-minute video. Presenter:
Aaditya Rai, on camera or narrating his own screen.

## Before recording (10 minutes ahead)

Timings below were measured on `main` @ `65404c9` (includes #150, tool-free
RAG generation) with `llama3.1:8b` on a laptop GPU.

1. Start Ollama, AI-Mode, RAG and MCP on the host, then Compose, per the
   [host services runbook](local-host-services-runbook.md). Run
   `python -m rag_service ingest --rebuild` after pulling, because other
   features add knowledge sources. Confirm `curl 127.0.0.1:8006/health`,
   `:8011/ready`, `:8012/health` and `127.0.0.1:18001/health` all return
   healthy.
2. Warm and pin the chat model at AI-Mode's context size, so the first answer
   is not a 10-15 s cold load:
   `curl -s 127.0.0.1:11434/api/generate -d '{"model":"llama3.1:8b","keep_alive":"60m","options":{"num_ctx":32768}}'`.
   Then run the grounded RAG query from the script once. `ollama ps` should
   list `llama3.1:8b` (context 32768) and `nomic-embed-text`. Each AI request
   resets Ollama's idle timer to 5 minutes, so after a longer pause between
   takes, ask one RAG question again first.
3. Open `http://localhost:8081/trips/trip_2026_melbourne_food_trail` and
   **hard refresh** (Cmd+Shift+R / Ctrl+Shift+R) so the current `app.js` loads.
4. Have one terminal ready in `ai-services/mcp-server` with the host venv.
5. Close anything showing personal data; use seeded trips only.

## Script (~2 min)

| Time | Action | Say |
| --- | --- | --- |
| 0:00-0:10 | Trip page for Melbourne Food Trail | "I own Trip & Itinerary and built the shared RAG server. Release 0 CRUD is unchanged: these trips and items still come from my database service." |
| 0:10-0:25 | **MCP, terminal:** `python -m tripgenie_mcp call trip_get_context '{"trip_id":"trip_2026_melbourne_food_trail"}'` (about 1 s) | "MCP runs on the host, outside Compose. It exposes the feature APIs as typed, read-only tools; here it returns my trip through my public API." |
| 0:25-0:50 | **MCP, website:** scroll to **Find options for this trip**, type country "Australia", click **Find trip options** (under 1 s). Point at the first card's `trip_get_context`, then the accommodation, activity, transport and budget cards, then "5 succeeded · 0 failed · 0 skipped. Nothing was saved." | "This is the same MCP server, now used from my website. The page calls my backend, and my backend calls the shared MCP server, which runs the registered tools: the same `trip_get_context` I just ran in the terminal, plus tools owned by Students 2 to 5. Each card shows the tool name, the arguments my backend sent and the structured result. It's read-only: nothing is saved, and options are added through the normal itinerary forms." |
| 0:50-1:05 | **RAG, terminal:** `curl -s -X POST 127.0.0.1:8011/query -H 'content-type: application/json' -d '{"query":"What are good day trips from Melbourne?","feature":"student-1"}'` (about 11 s warm) | "This is the RAG server called directly on localhost: the answer, its confidence category and the citations it is grounded in." |
| 1:05-1:35 | **RAG, website:** knowledge-base panel, "What are good day trips from Melbourne?" (about 16 s; narrate during the wait, then point at the confidence badge and citation card) | "The backend calls the host RAG server, which embeds the question through AI-Mode, searches my feature's documents plus shared ones, and only then generates. The confidence comes from the retrieval score, and every citation must be one of the chunks that were retrieved." |
| 1:35-1:48 | Ask "How do I bake sourdough bread?" (about 1 s) | "When nothing relevant is retrieved, generation is skipped and it says so rather than guessing." |
| 1:48-2:00 | Close | "Compose runs only feature containers; CI runs with MCP and RAG disabled; evidence is in our Release 1 register." |

The trip-options panel is labelled "AI mode · trip tools" on screen, so say
"MCP" out loud when it appears; the tool names on each card (`trip_get_context`,
`accommodations_search`, `activities_search`, `transport_search`,
`budgets_list`) are the visible proof that the website is using MCP.

If the grounded answer is still loading at 1:30, cut to the pre-recorded
take or the [screenshot](evidence/student-1/screenshots/02-rag-grounded.png)
and say so; do not present a screenshot as live.

Keep Release 0 AI suggestions out of this segment: they take about 76 s and
the `llama3.1:8b` drafts are thin. If the group wants them shown, start the
request before the segment and cut to the result. The terminal RAG step
covers the brief's "local terminal validation of the MCP and RAG servers";
agree with the group so it is shown once in the video, not by every member.

## Q&A preparation

- **MCP tool boundaries.** The Student 1 backend calls a fixed list of five
  read-only tools with server-side input schemas that reject extra
  arguments; unknown tools are rejected. Results are shown, never persisted;
  users add options through normal CRUD. `budgets_get_summary` is avoided
  because it fans out back into this service.
- **Why RAG calls AI-Mode, not the reverse.** AI-Mode owns model policy
  (allowlists, timeouts, Ollama access). RAG is a client for embeddings and
  generation, so there is one gateway to Ollama and RAG stays testable with
  fake transports.
- **Citations and confidence.** The model returns citation ids; the server
  rejects any id not in the retrieved set (`502`) and resolves titles, sections
  and paths from index metadata. Confidence is server-calculated: ≥0.8 high,
  ≥0.7 medium, otherwise low, calibrated from measured query scores.
- **Insufficient context.** Two paths: best score under 0.5 skips generation
  (sourdough, 0.43); above it, the model may still declare the context
  insufficient (live weather in Lisbon, 0.61). Both return the fixed message
  with no citations.
- **CI disabled modes.** CI sets `STUDENT1_BACKEND_RAG_ENABLED=false` and
  `..._MCP_ENABLED=false`, checks the routes return `503 RAG_DISABLED` /
  `503 MCP_DISABLED`, and fails if Compose defines AI-Mode, MCP, RAG, Ollama
  or the agentic loop. RAG tests use fakes; no model runs in CI.
- **Why AI-Mode, MCP and RAG are outside Compose.** Release 1 requires them as
  shared host services; containers reach them via `host.docker.internal`.
- **Release 1 vs Release 2.** Release 1 is read-only discovery and grounded Q&A
  shown to the user. Tool-driven itinerary writes or autonomous planning are
  not part of Release 1.
- **Bugs found and fixed.** Release 0 suggestions broke because Ollama's
  grammar rejected some JSON schema constructs and the backend mis-parsed
  AI-Mode errors carrying a tool trace (#147). Frontend requests timed out
  before local models finished, so client timeouts were raised (#145). RAG
  thresholds were recalibrated and the model's insufficient-context verdict
  is now honoured (#144).
