# ADR 0006: MCP-owned feature tool catalogues

Status: Accepted

## Context

Feature assistants and the shared Planner use MCP descriptions and input schemas
for model-directed retrieval. A feature selects its relevant catalogue through a
single `feature` value, keeping membership alongside tool registration instead
of maintaining lists in each feature backend.

## Decision

1. MCP advertises `_meta.tripgenie.owner` and `_meta.tripgenie.features` on each
   tool. Ownership also determines the result envelope's `source`. Shared trip
   tools are included for each student feature. Trip discovery and budget cost
   integrations are represented as additional memberships in MCP.
2. AI-Mode accepts optional `feature` (`student-1` through `student-5`) on
   `/generate` and `/generate-plain`. It discovers all MCP pages, selects matching
   tools, and applies context bounds to the selected catalogue. Native execution
   and reference-only generation use the same selection. Requests that omit the
   selector retain the complete catalogue.
3. Only selected names can execute through that generation request. Unknown or
   out-of-scope tool calls are rejected before MCP execution; argument validation,
   execution limits and partial traces keep their existing behavior. Membership
   selects domain availability; prompts continue to specify requested actions.
4. AI-Mode returns `available_tools` from the actual discovery snapshot. Plain
   generation without catalogue reference returns an empty snapshot and does not
   contact MCP. No additional inference round is needed to discover membership.
5. The Multi-Agent Server forwards its existing `feature` to AI-Mode and records
   catalogue snapshots in its steps. Planner tool names are checked against its
   snapshot; deterministic Worker membership checks use the Worker's snapshot.
   Successful catalogue/tool stages require a nonempty valid snapshot. The
   request contract uses feature membership only; caller-maintained tool lists
   are rejected. Existing saved requests are migrated at startup without
   changing their workflow or audit history.
6. Student 4 sends its feature on normal MCP generation and Smart Planner requests.
   Its backend and frontend retain stage snapshots in workflow history. The
   Worker's feature prompt remains unchanged.

## Integration

Roll out MCP metadata first, then AI-Mode, the Multi-Agent Server, and feature
clients. Deploy the updated Student 3 and Student 5 callers with the shared
server so they use the feature-only request contract. Normal generation clients
can continue without the optional AI-Mode selector.
Other feature backends can opt into normal generation scoping with their own
student identifier; multi-agent callers already supply that identifier.

Direct trusted MCP clients continue to discover the complete tool catalogue.
Feature ownership, public HTTP providers, data persistence, RAG and deployment
settings remain unchanged.

See [the Multi-Agent contract](../release-2-multi-agent-contract.md),
[AI-Mode](../../../ai-services/ai-mode/README.md) and
[MCP membership](../../../ai-services/mcp-server/README.md#feature-membership).
