# Planning transport and availability

How transport becomes part of a trip in TripGenie, and how availability and
capacity affect what can be planned. Adding transport to a trip records a
planning selection: it does not book a seat with the carrier.

## Transport planning: adding transport to a trip

Transport is added to a trip from the transport option's own page by
choosing the trip and the number of travellers. The trip itinerary feature
stores which transport belongs to which trip, while the transport feature
keeps the option's route, times, and price. Adding the same option to the
same trip again replaces the earlier selection instead of creating a second
one, so a double submission cannot plan the same party twice. An AI
suggestion never adds transport by itself; a traveller always adds it.

## Transport planning: plan status meanings

Each transport selection on a trip has a plan status. Pending means the
option is shortlisted and still being considered. Confirmed means the
traveller has committed it to the itinerary. Cancelled means it has been
removed from the plan but is still shown in the trip's history. Completed
means the journey has been taken. Plan statuses describe the traveller's
plan only; they are not booking or ticket states from the carrier.

## Transport availability: availability status

Each transport option has an availability status set by its operator.
Available means seats can be planned normally. Limited means few seats are
left, so plan early. Sold out means no more seats are offered. Cancelled
means the service will not run. An option that is sold out or cancelled
cannot be added to a trip, even if its seat count looks positive, because
availability is declared by the operator and not derived from the seat count.

## Transport capacity: seats remaining

Each option has a capacity, and TripGenie shows the seats remaining after
subtracting the travellers already planned on it across all trips; cancelled
selections do not use seats. A selection that would plan more travellers than
there are seats left is refused. When the trip itinerary service cannot be
reached, seats remaining is shown as unknown rather than as zero or full,
because an unknown count must not look like a sold-out or an empty service.
Seat counts guard planning data and are not a live inventory guarantee.

## Transport planning: removing and deleting transport

Removing transport from a trip deletes that selection from the trip. A
transport option that any trip still holds cannot be deleted from the
catalogue; remove it from those trips first. If the trip itinerary service is
unavailable the delete is allowed to proceed, so catalogue maintenance is not
blocked by another service's outage.

## Transport planning: when other services are unavailable

Browsing, filtering, and comparing transport keep working when the trip
itinerary service or the AI services are unavailable. Planning transport
onto a trip needs the itinerary service, so it reports that service as
unavailable instead of failing silently. AI suggestions, MCP tool lookups,
and the transport guide are optional helpers: when one is switched off or
unreachable it says so, and the rest of the transport feature still works.
