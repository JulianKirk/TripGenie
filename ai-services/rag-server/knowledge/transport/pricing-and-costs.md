# Transport pricing and cost estimates

How TripGenie prices transport options and estimates what transport adds to a
trip. Transport prices are listed in Australian dollars (AUD) unless the
deployment is configured for another ISO currency. Every figure is a planning
estimate, never an amount that has been charged.

## Transport pricing: per traveller and per vehicle

Each transport option has a pricing basis. A per-traveller price is charged
for every person travelling, so the estimated cost is the listed price
multiplied by the number of travellers. A per-vehicle price is charged once
for the whole vehicle, so the estimated cost is the listed price whatever the
party size. For example, a per-traveller flight listed at 189.00 AUD costs
378.00 AUD for two travellers, while a per-vehicle car rental listed at
240.00 AUD still costs 240.00 AUD for four travellers. The pricing basis is
not decided by the type: a shuttle transfer can be sold per seat while a car
hire of the same size is sold per vehicle.

## Transport pricing: why a car rental is not multiplied

A car rental is usually priced per vehicle, so TripGenie does not multiply
its price by the number of travellers. Multiplying a whole-vehicle hire by
the party size would overstate its cost by the number of people sharing the
car. This is why a group of four can find a car rental cheaper per person
than four separate train or bus fares, even when the rental's listed price is
higher than one fare.

## Transport costs: the estimated cost of one selection

When a transport option is added to a trip, TripGenie derives its estimated
cost from the option's price, its pricing basis, and the number of travellers
on that selection. The estimate is not stored or typed in, so it can never
contradict the option it belongs to. It is calculated in whole cents so that
a long itinerary does not drift by fractions of a cent.

## Transport costs: the trip transport total

A trip's transport total adds up the estimated costs of its active
selections only. Selections that are pending, confirmed, or completed count
toward the total; a cancelled selection is still listed with the trip but is
excluded from the total. The trip transport summary reports the number of
entries, the number of active entries, the estimated total, and its currency.

## Transport costs: how the budget uses transport costs

The TripGenie budget feature reads a trip's transport total, with its
currency, as committed transport cost. Because the total excludes cancelled
selections and respects each option's pricing basis, the budget sees the same
transport figure that the trip's transport page shows. These remain planning
estimates for the budget, not payments made to a carrier.

## Transport prices: filtering by price

A price filter compares each option's listed price, not the total for the
party. A minimum price above the maximum price is rejected rather than
returning nothing, and prices are limited to two decimal places. Because the
filter uses the listed price, a cheap per-traveller fare can still cost more
than a per-vehicle option for a large group, so compare party totals before
deciding.
