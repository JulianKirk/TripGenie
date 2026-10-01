# Adding a stay to a trip

How an accommodation listing becomes a stay on a TripGenie trip. Trips and
their itineraries are owned by the trips feature; the accommodation feature
adds and removes stays through it.

## Stays: adding accommodation to a trip

Open a listing and choose Add to Trip. The form lists every trip and ticks
the ones that already hold this listing. Pick a trip, set the check-in and
check-out dates, and optionally a check-in and check-out time, then save. The
stay is stored on the trip's itinerary, not in the accommodation catalogue.

## Stays: check-in and check-out dates

The date inputs are limited to the trip's own start and end dates. A stay
outside the trip is rejected by the trips feature, and its message is shown
on the form so the dates can be corrected. If no check-in date is given, the
stay starts on the trip's first day.

## Stays: the nightly total on the form

While dates are being chosen, the form shows the number of nights and the
total for the stay, calculated from the listing's price per night. A
check-out date before the check-in date shows no total.

## Stays: removing a stay

A stay lives on the trip's itinerary, so removing it from the trip removes
it from the itinerary and also removes its amount from the trip's committed
accommodation cost, because that cost is worked out from the stays currently
on the trip. Deleting or editing a listing in the catalogue is a separate
action from removing a stay.
