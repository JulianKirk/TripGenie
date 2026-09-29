# ADR 0003: Activity agent permissions and presentation over shared MCP

Status: implemented on Student4/AddActivitiesServiceMcp; pending review/merge.

The Release 1 rubric requires frontend MCP access through the feature backend,
structured tool results, and defined tool boundaries. The team additionally wants
external clients to manage activities through MCP. These are separate consumers
with different capabilities; advertising a write tool must not grant the UI agent
permission to execute it.

The shared host MCP server exposes activity search/detail/category/cost reads and
create/update/delete. Its tools wrap Student 4 public APIs, never persistence
models or AI orchestration routes. MCP records are general-purpose wire contracts,
independent of TripGenie's frontend. External local clients are trusted; the server
does not claim user authentication. Delete requires explicit confirmation and
uncertain write outcomes are reported without automatic retries.

Student 4's backend owns a read-only allowlist. It discovers MCP schemas, restricts
them to allowed tools, constrains AI-Mode output using those schemas, then validates
and checks policy again before execution. Trip tools are scoped to the selected
trip. Six model steps, bounded tool calls, result/context limits and a total deadline
prevent unbounded execution. Each request starts with empty state. AI-Mode remains
the sole Ollama adapter. Its schema-constrained generation contract gains an optional
`system` field for trusted policy, separate from user/tool context in `prompt`.
Both fields share the existing input character budget. Existing clients can omit
`system`; no native tool-call API or retained chat history is added. The assistant
places the current question after tool context and uses contrasting syntax examples
to reduce accidental copying of example filters. Model quality still varies;
generated prose and semantic matching remain advisory.

Final model output contains plain text and typed activity references. Only IDs
returned by successful activity tools in that request can become cards. The backend
refetches details through MCP, while the frontend renders authoritative records and
existing explicit itinerary actions. This prevents invented cards; it cannot prove
every assertion in generated prose is correct. No model HTML is rendered.

The backend now retains explicit request constraints independently of generated
tool arguments. A conservative parser accepts supported AUD bounds, party sizes,
ISO dates and local time windows; conflicting or ambiguous forms receive an
authored clarification. Selected-trip data supplies missing party size and dates.
Search arguments are reconciled with these constraints, and authoritative MCP
results are checked for exact Decimal party cost, participant limits,
accessibility and catalogue schedule overlap. Final detail reads repeat those
checks so a changed price or schedule cannot retain an invalid card. Schedule
matching is not a reservation or proof of remaining capacity.

For constrained activity results the backend writes the verification summary and
party totals, replacing model prose that could still endorse excluded records.
If the model omits card references, at most six eligible request-local IDs are
freshly resolved. Other factual prose and semantic location/category selection
remain model-assisted. Bounded pages cannot establish that the entire catalogue
has no suitable activity. These checks belong to feature orchestration; external
MCP clients still receive general catalogue contracts. Small keyword variants
such as kayaking/kayak live in the public catalogue search implementation so all
clients receive the same behavior.

The UI's expandable Tools used section comes from backend execution records, not
model descriptions. It shows names, arguments, statuses, durations, result IDs and
correlation IDs, including card lookups and failures. Correlation travels in
X-Request-ID through MCP to provider APIs. Failed MCP requests do not fall back to
the former direct search pipeline. Legacy plan/evaluate endpoints are retained for
compatibility and ordinary CRUD/browsing remains available.

Deployment places AI-Mode alongside MCP and RAG on the host; all five backends'
Compose AI-Mode URLs and host mappings migrate together. Only Student 1 and Student 4
public ports are newly published on loopback for trip/activity MCP tools. Databases
remain private. Native Linux uses a restricted bridge interface for host-service
access; DNS-rebinding protection includes the configured bind host. Student 4 CI
disables runtime MCP/RAG while testing protocol behavior with deterministic
transports. RAG UI and shared validation-loop implementation remain separate work.
