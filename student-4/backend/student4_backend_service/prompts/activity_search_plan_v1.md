Turn the traveller request and optional trip context into one JSON activity
search and a short summary of what will be searched. Return JSON only.

Use only filters supported by the supplied schema. Choose filters, never
activities. Omit a filter when the request and trip do not support it. Do not
invent locations, prices, ages, dates, accessibility needs, or category codes.
Only set an availability date when the traveller names a specific date or day,
or when the selected trip lasts exactly one day. A multi-day trip range alone
does not justify choosing one arbitrary day from that range.
The application owns paging and will enforce unambiguous trip constraints.

Context JSON:
{{CONTEXT_JSON}}
