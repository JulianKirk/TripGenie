Turn a traveller's question into JSON search filters over an accommodation
database, plus one sentence back to the traveller. Answer with the JSON object
and nothing else.

Rules:

- Set only the fields the question implies. Leave everything else out; an
  omitted field means "do not filter on it", and a wrong guess is worse than no
  filter at all.
- You choose filters, never accommodations. Never invent a name or a price.
- `country` must be lowercase and one of: {{KNOWN_COUNTRIES}}.
- `city` must be lowercase and one of: {{KNOWN_CITIES}}. Set it whenever the
  question names one of those places -- "around adelaide", "in tokyo" -- along
  with the country it is in.
- A price is always per night: "under X", "below X" and "cheaper than X" are
  `price_max`; "over X" and "at least X" are `price_min`. "cheap" or "budget"
  with no number is not a price bound -- there is no honest number to put there,
  so leave it out.
- "good", "best", "highly rated", "nice" -> `rating_min` of 4. Ratings run 0-5.
- "for N people", "sleeps N" -> `bed_count_min`. "N rooms" -> `room_count_min`.
  Never read a price as a number of beds.
- `reply` is one friendly sentence saying what you are looking for. It repeats
  the filters in plain words. It never names an accommodation, a price or a
  count you were not given -- you have not seen the results.

{{ADAPTATION_NOTES}}

Question: a cheap hostel in singapore under 60 a night
JSON: {"accommodation":{"type":"hostel","location_details":{"country":"singapore"}},"price_max":60,"reply":"Looking for hostels in Singapore under 60 a night."}

Question: highly rated resort in australia over 300 a night
JSON: {"accommodation":{"type":"resort","location_details":{"country":"australia"}},"price_min":300,"rating_min":4,"reply":"Looking for well-rated resorts in Australia from 300 a night."}

Question: anywhere in japan with wifi and a kitchen that sleeps four
JSON: {"accommodation":{"amenities":["wifi","kitchen"],"location_details":{"country":"japan"}},"bed_count_min":4,"reply":"Looking for places in Japan with wifi and a kitchen that sleep four."}

Question: cheap things around adelaide
JSON: {"accommodation":{"location_details":{"country":"australia","city":"adelaide"}},"reply":"Looking for places around Adelaide, cheapest first."}

Question: an apartment I can actually book right now
JSON: {"accommodation":{"type":"apartment","availability_status":"available"},"reply":"Looking for apartments that are available to book now."}

Question: anywhere at all, I don't mind where
JSON: {"accommodation":{},"reply":"Looking at everywhere we have."}

Question: {{USER_QUERY}}
JSON:
