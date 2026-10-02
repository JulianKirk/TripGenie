# Student 1 frontend screenshots

Captured 2026-10-02 (UTC) with a Playwright-driven Chromium browser at
`http://localhost:8081/trips/trip_2026_melbourne_food_trail` (Compose
`student-1-frontend`, main `aec615c`), viewport 1280x900. Before capture,
`/static/js/app.js` and `/static/css/styles.css` were re-fetched with
`cache: 'reload'` and the page reloaded; the served `app.js` (1,358 bytes)
matched the repository file. Times are measured from the button click to the
rendered result.

| # | Screenshot | Action | Expected | Actual | Time |
| --- | --- | --- | --- | --- | --- |
| 1 | [01-trip-overview.png](screenshots/01-trip-overview.png) | Open the Melbourne Food Trail trip | Trip list and detail render from the backend | Rendered (UI mode, trip summary, filters) | - |
| 2 | [02-rag-grounded.png](screenshots/02-rag-grounded.png) | Ask "What are good day trips from Melbourne?" | Answer, confidence badge, citations | "High confidence", answer, 1 source (Destination Guides, Melbourne section), 5 of 5 chunks, run and correlation ids | 26.2 s |
| 3 | [03-rag-insufficient.png](screenshots/03-rag-insufficient.png) | Ask "What is the live weather in Lisbon right now?" | Insufficient-context state, no answer text or sources | "Insufficient context · Not enough information to answer", no sources | 32.5 s |
| 4 | [04-mcp-australia.png](screenshots/04-mcp-australia.png) | Find trip options with country "Australia" | Five tool cards, nothing saved | "5 succeeded · 0 failed · 0 skipped. Nothing was saved." Cards for Students 1-5 tools | 1.4 s |
| 5 | [05-mcp-no-country.png](screenshots/05-mcp-no-country.png) | Find trip options with country blank | Location searches skipped with a reason | 3 OK, 2 "Skipped" (accommodations/activities) with the country reason | 0.9 s |
| 6 | [06-ai-suggestions.png](screenshots/06-ai-suggestions.png) | Release 0 draft suggestions for 2026-11-13, "Plan a relaxed food-focused day", "food, markets" | Drafts with `persisted=false`, approval required, review-then-save action | 2 drafts (llama3.1:8b, prompt asset v2), each `persisted=false` + "Review and save via CRUD" | ≤ 46 s |

Notes:

- Row 6's time is an upper bound: completion was polled every 5 s.
- An earlier attempt at row 6 ended with `net::ERR_NETWORK_IO_SUSPENDED` in
  the browser console because the capture session was interrupted; it was
  not a server failure. The retry above succeeded.
- Screenshots contain only seeded demo data.
