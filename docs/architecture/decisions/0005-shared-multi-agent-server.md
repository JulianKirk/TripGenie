# ADR 0005: Shared Multi-Agent Server with human-gated results

- Status: Accepted
- Date: 2026-10-20
- Release: 2

## Context

Release 2 requires one shared, non-containerised Multi-Agent Server that every
feature calls through its backend/API and that also runs from the terminal. It
must coordinate Planner, Worker and Reviewer agents, end every workflow with a
human decision (approve, correct, partially accept or reject), and keep a
workflow history with coordination/audit logs as evidence.

The constraints already in place:

- AI-Mode is the only service that talks to Ollama (ADR 0004). It owns the
  model-directed MCP tool loop behind `/generate` and a tool-free
  `/generate-plain`.
- Every feature already sends AI-Mode a prompt, a response schema, a
  correlation id and metadata, and grounds answers against the returned
  `tools[]` trace (accepting only ids a successful tool from its own source
  returned).
- The local model (`llama3.1:8b`) takes 10–60 s per call; a three-agent chain
  plus a revision cannot fit one browser request.

## Decision

1. **Agents are roles over AI-Mode, not new model adapters.** The Planner and
   Reviewer each make one `/generate-plain` call with their own versioned
   prompt and response schema. The Worker makes one `/generate` call, so it
   uses the same MCP catalogue, limits and traces as every other feature.
   The Planner sets `tool_catalogue: true`: AI-Mode discovers the MCP
   catalogue exactly as for `/generate` and appends the tool names,
   descriptions and argument schemas to its system message as reference
   text, without offering them as callable functions. The Planner can then
   name real tools and arguments without the tool loop, which would let it
   execute tools and lose the plan's schema-constrained reply. Tool
   definitions are never copied into multi-agent prompts; MCP stays their
   only source.
2. **Deterministic checks sit between the Worker and the Reviewer**: the
   feature's output schema, grounding of every declared id against successful
   tool results from that feature's source, allowed tools only, no write
   tools, and at least one successful tool call. A failed check stops the
   Reviewer approving and triggers the one permitted revision, so a model's
   opinion is never the only safeguard.
   A revision goes back to the Planner, not only the Worker. Most live
   failures were tool calls with wrong arguments (for example an integer sent
   as a string), which AI-Mode rejects; with llama3.1:8b the model rarely
   corrects them inside the tool loop and the Worker's call fails. That
   failure is reviewed rather than ending the run, and the Planner gets the
   rejected calls and the review so it can correct the plan against the tool
   schemas. Only model failures (`BAD_GATEWAY`) are retried; outages and
   timeouts are not, and an attempt that ran a write tool is never repeated.
3. **Runs are asynchronous.** `POST /runs` returns `202` and the workflow runs
   in the background; callers poll `GET /runs/{id}`. The state machine is
   `planning → working → reviewing → awaiting_human → completed | rejected`,
   with `reviewing → planning` on a revision and `failed` from any stage.
4. **Human review is the only way a run finishes successfully.** The server
   never writes feature data. Changes the Worker proposes are returned as
   `proposed_actions`; after a human approves (or partially accepts), the
   feature backend performs them through its own routes.
5. **History is a local SQLite store in WAL mode** with an append-only event
   log, exported as JSON or Markdown for the report and the agentic loop.
6. **Feature prompts lead.** The Worker's system prompt is the feature's own
   prompt followed by the workflow rules, and the feature's context keys are
   sent at the top level of the Worker's message. Live tests showed the
   reverse order stops the 8b model calling the feature's tools. Optional
   `feature_instructions` carry role-neutral domain policy to all three agents,
   including revisions. They follow each role's own system instructions; the
   Worker still leads with its feature prompt, then common policy and workflow
   rules. Planner/Reviewer never receive Worker-only output/tool instructions.
   The common policy shares the existing Worker instruction allowance and counts
   against each stage budget; no additional model calls are introduced.

## Consequences

- Features integrate with one small HTTP client and keep owning their prompts,
  schemas, grounding rules and writes.
- The workflow is slower than a single `/generate` call (about 60–160 s
  locally), so UIs poll and show each stage as it completes.
- Run history survives restarts; runs interrupted by a restart are marked
  `failed` rather than left `working`.
- Like AI-Mode, the server has no authentication and binds to loopback. It is
  disabled by default in the cloud baseline (each backend's
  `..._MULTI_AGENT_ENABLED=false`).
- The contract is documented in
  [`../release-2-multi-agent-contract.md`](../release-2-multi-agent-contract.md).
