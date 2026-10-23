# Student 1 Multi-Agent runtime evidence

**23 October 2026.** Four independent real-model browser runs completed through
the Student 1 Docker Compose frontend, backend and database, with MCP,
AI-Mode, Multi-Agent and Ollama on the Windows host. All four human decisions
worked. This is functional evidence, not a final release approval or a claim
that every generated plan is correct.

## Version and configuration

PR #189, based on `63ecdc9`, plus the prompt clarification and runbook update
committed with this report. No shared server code or global model default was
changed. The dedicated Compose project had its own database volume and ports;
the original checkout and other application data were not modified.

- Windows; NVIDIA RTX A2000 Laptop GPU, 4 GB VRAM; real Chrome via Playwright.
- Ollama `qwen2.5:3b`, a separately downloaded tool-capable model.
- `AI_MODE_DEFAULT_MODEL=qwen2.5:3b`; the model is in `AI_MODE_ALLOWED_MODELS`.
- `AI_MODE_CONTEXT_TOKENS=12288`, `AI_MODE_TIMEOUT_SECONDS=90`,
  `AI_MODE_AGENT_TIMEOUT_SECONDS=180`, `MULTI_AGENT_MODEL=qwen2.5:3b`.
- Normal stage deadlines: Planner 90 s, Worker 200 s, Reviewer 60 s,
  overall run 600 s. No output-token ceiling.
- AI-Mode connected **directly** to Ollama, without the diagnostic proxy,
  injected model replies or replayed responses.
- Frontend `18353`, backend `18301`, internal database `8002`; host MCP
  `18312`, AI-Mode `18306`, Multi-Agent `18313`, Ollama `11434`.
- The container reached the host server through `host.docker.internal`.
  Its `/ready` check passed after installing the missing configured
  `nomic-embed-text` model. This does **not** establish RAG functionality.

The reusable startup profile, using the ordinary ports, is in the
[host services runbook](../release-1/local-host-services-runbook.md#student-1-profile-for-a-4-gb-gpu-windows-powershell).

## Scenario and results

Each run used a new synthetic Singapore trip, 12-14 November 2026, containing
one saved dinner on 14 November. The browser submitted:

> Draft exactly two general travel-preparation notes: check travel documents
> on 2026-11-12, and pack a day bag on 2026-11-13. These are new general notes,
> not bookings or saved activities. Use category note, null times, and no
> invented venue.

These are **general notes**, for which a null `source_id` is allowed. The
Worker genuinely read the trip through MCP. This scenario does not prove
accurate citations for saved bookings or cross-student itinerary planning.

| Human decision | Run ID | Time to human review | New saved items |
| --- | --- | ---: | ---: |
| Approve all | `magent_8584e4aef5f5` | 46.3 s | 2 |
| Save corrections | `magent_7d060706226f` | 25.0 s | 2 |
| Save selected | `magent_6e4a5b75d58e` | 25.1 s | 1 |
| Reject | `magent_ff28106d8d8b` | 28.2 s | 0 |

For **each** run, the browser reached `awaiting_human`, the actual Reviewer
approved, all deterministic checks passed, and the two proposed dates matched
the request. A successful `trip_get_context` call was present. The backend API
still showed only the original dinner before the human decision.

After clicking the real form button, API read-back confirmed the saved count.
Correction persisted the edited title `Human-corrected preparation`. Partial
acceptance saved only `item_<run_id>_0`. Replaying the exact submitted form
created no duplicates; saved items were reported as already on the itinerary.
A conflicting decision returned HTTP 409 on every run. The four disposable
trips were then deleted through the backend API.

These are observed elapsed times, not a performance guarantee.

## Evidence

[Results](student-1-runtime-evidence/results.json) and unedited server audit
exports contain the actual run IDs, model stages, tool evidence, checks,
history and human decisions:

- [Approve](student-1-runtime-evidence/approve-audit.json)
- [Correction](student-1-runtime-evidence/correct-audit.json)
- [Partial](student-1-runtime-evidence/partial-audit.json)
- [Reject](student-1-runtime-evidence/reject-audit.json)

The [terminal output](student-1-runtime-evidence/terminal-show.txt) was captured
with the real server still running:

```powershell
python -m multi_agent_service --url http://127.0.0.1:18313 show magent_8584e4aef5f5
```

Browser captures:
[before approval](student-1-runtime-evidence/approve-before.png),
[approved](student-1-runtime-evidence/approve-after.png),
[corrected](student-1-runtime-evidence/correct-after.png),
[partially accepted](student-1-runtime-evidence/partial-after.png),
[rejected](student-1-runtime-evidence/reject-after.png).

To reproduce, start the runbook stack with the profile above, create the
synthetic trip and dinner, and submit the quoted request through **Plan my
itinerary**. Use a separate run for each decision. Compare the itinerary before
and after, repeat the same submission, attempt a different decision, and
export each run. Never approve a draft simply because the model approved it.

## Investigation and remaining limitations

Earlier `llama3.1:8b` runs timed out after the Planner completed. In one run,
the two successful MCP reads took only 109 ms and 78 ms; the Worker then
waited roughly 15 minutes for generation. A bounded diagnostic observed slow,
long post-tool output. A separate schema-formatting probe completed in 57 s,
so schema compilation was **not** established as the cause. An additional
8b/8192-context attempt hit the 90 s Planner deadline. Hardware pressure,
output length and model behaviour remain contributing possibilities, not a
proven single root cause.

The smaller model restored usable runtime, but it also produced failures:

- A request for preparation reminders tied to the saved dinner lost the
  requested source IDs; another attempt put both reminders on the dinner's
  date. The Reviewer incorrectly approved those drafts. The prompt now
  clarifies that a note about a saved item still needs its source ID; that
  clarification alone did **not** eliminate the observed quality problem.
  [Captured failed reminder run](student-1-runtime-evidence/failed-saved-reminders.json).
- An earlier general-note run produced no items, then its revision attempted
  unrelated `activities_create` calls with invalid arguments and an
  unavailable transport search. The calls did not create activities; the
  `allowed_tools` and `no_writes` checks failed and the acceptance check stopped.
  [Captured failed revision](student-1-runtime-evidence/failed-note-revision.json).

Thus the successful four-run scenario is not a reliability claim for arbitrary
requests. Review dates, citations and actual tool traces before recording.
`grounding` validates referenced IDs, not the semantics of every sentence or
the absence of a missing citation. A null citation on a general note is not
proof of booking provenance.

On this server version, read-only Worker instructions and post-call checks are
**not preventive tool authorization**: AI-Mode still advertises the full MCP
catalogue. Open PR #197's scoped catalogue is directly relevant, but was not
merged or imported into this evidence. It also removes the `allowed_tools`
request field, so Student 1 must be updated if that shared contract lands first.

Fifty focused Student 1 backend/frontend regression tests passed after the
prompt clarification. RAG, a final cloud deployment, Claude agentic-loop reviews
and the team's final release decision are separate acceptance work.
