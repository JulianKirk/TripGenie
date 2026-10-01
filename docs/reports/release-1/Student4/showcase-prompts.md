# Activity assistant showcase prompts

## Activity search

> Show me kayaking activities in Sydney.

## Search, then get full details

> Find the Sydney Harbour sunrise kayak activity, then look up its full details and tell me its weekly schedule and booking notes.

Expand **Tools used** to check the actual MCP calls. The first prompt demonstrates
`activities_search`; the model can also choose a detail lookup. The second should
show `activities_search` and `activities_get`, with the schedule and booking notes
visible in the answer. The model must choose the detail call and describe its results. The backend
does not add a detail call or rewrite the answer if the model misses it.

## Activity guides (RAG)

Select **Activity guides (RAG)** in the assistant panel.

> What should I bring on a sunrise kayak or snorkelling trip?

> How is the total cost worked out for four people on a per-person activity versus a flat-admission one?

Each should show a confidence badge and a **Sources** list citing the indexed
activity guides or Student 4 documentation.

> Which laptop is best for learning to program?

This should show the insufficient-context notice and no sources.
