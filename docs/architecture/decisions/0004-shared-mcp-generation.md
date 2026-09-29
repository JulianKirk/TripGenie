# ADR 0004: Shared model-directed MCP generation

Status: implemented on Student4/AddActivitiesServiceMcp; pending review/merge.
Supersedes ADR 0003's feature-local agent loop and deterministic recommendation rules.

The shared AI-Mode `/generate` endpoint now owns the model/MCP conversation. All
callers get the full dynamically discovered MCP catalogue, including write tools.
The native Ollama chat interface returns tool calls; shared AI-Mode validates and
executes them, returns actual results to the model, and returns its final answer.
MCP remains the owner of tool descriptions, schemas and public-API integration.
AI-Mode stays in Compose; MCP and Ollama run on the host. Backends retain
`http://ai-mode:8006`, and AI-Mode reaches MCP through the host gateway.
RAG retains its existing host process and reaches AI-Mode on published loopback
port 8006. This supersedes ADR 0003's host AI-Mode deployment.
`/embed` retains its numerical embedding behavior and does not require MCP.
Ollama requests retain the existing SDK. Health and embedding methods are unchanged.
Native chat uses its pinned lower-level request helper to preserve complete MCP
schemas on every tool round, bypassing only the high-level tool serializer that
drops nested schema fields. SDK transport and response validation remain in place.

This avoids implementing the same loop separately in each student backend. No new
process or endpoint is introduced. Existing generation request fields and final
response fields remain; an additive `tools` trace reports actual returned data.
Errors preserve partial traces. A failed run does not imply rollback of writes.
Schema-constrained final formatting is another model call with tools disabled, not
application-authored prose. Native tool selection is separate from the final JSON
schema so output grammar does not prevent tool requests.

Student 4 supplies its system prompt and response schema and resolves grounded
activity references for display. It no longer parses natural-language constraints,
rewrites model arguments, filters recommendations, forces detail reads or replaces
model answers. Quality improvements belong in prompts and MCP descriptions.
The superseded plan/evaluate endpoints, prompts and deterministic filter parser
are removed. The trip-context directory remains available for the assistant picker.

All advertised tools are available: the previous read-only/selected-trip execution
allowlist is deliberately removed. Trusted instructions direct writes only for
explicit requests, but prompts are not hard authorization. This remains a trusted
local deployment without a new authentication/approval layer. Protocol/schema
validation, fixed MCP URL, request deadlines, context limits and duplicate-call
protection remain. Unknown or invalid tools are never executed. There are no
automatic retries of uncertain writes.

Generation now requires MCP even when the eventual answer makes no tool calls.
Existing `/health` and `/ready` continue reporting the Ollama chat/embedding model
baseline; MCP failure is reported explicitly by `/generate` and does not disable
`/embed`. Consumers must allow enough time for multiple model/tool turns.
RAG's strict generation decoder accepts the additive trace; RAG still validates
citations against its retrieved context. Tool data alone is not a RAG citation.

Tests use injected HTTP transports and real MCP SDK sessions. Local functional
checks exercise actual model decisions and UI traces. No new CI/CD integration is
introduced, and development evidence remains outside the repository.
