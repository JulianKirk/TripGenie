# Choosing transport for a trip

General guidance on choosing and comparing transport options in TripGenie.
TripGenie lists transport options for planning only. It does not book seats,
issue tickets, take payments, or hold reservations with any carrier; the
traveller arranges the journey directly with the provider.

## Transport types: what each type means

Every transport option has one of six types. A flight is an air journey
between two airports. A train is a rail journey between two stations. A bus is
a scheduled coach or bus service. A ferry is a scheduled water crossing. A car
rental is a hired vehicle collected from a depot and driven by the traveller.
A transfer is a pre-arranged shuttle or private ride, usually between an
airport and a hotel. The type describes the kind of journey only; it does not
decide how the option is priced, which is set separately by its pricing basis.

## Transport types: which type suits a journey

Flights are usually fastest for long distances but add airport time before
departure and after arrival. Trains and buses are often cheaper for shorter
journeys and travel city centre to city centre. Ferries suit island and
harbour crossings. A car rental gives flexibility for regional touring and
day trips where public transport is limited, and a group sharing one vehicle
can make it cheaper per person. A transfer is the simplest way to reach
accommodation from an airport, especially when arriving late or with luggage.

## Transport comparison: comparing options side by side

TripGenie can compare up to four transport options side by side. The same
option cannot appear twice in one comparison, and an option that does not
exist is reported as missing rather than silently dropped, so a comparison
always shows every option that was asked for. When comparing, look at the
total cost for the whole party rather than the listed price alone, the
journey duration, the departure and arrival times, the availability status,
and the seats remaining.

## Transport comparison: journey duration and time zones

The journey duration in minutes is calculated by TripGenie from the departure
and arrival times. When an option records UTC offsets for its departure and
arrival, the duration accounts for the time zone change, so a flight that
crosses time zones shows its real time in the air rather than the difference
between the two local clock times. Duration is derived, never entered by
hand, so it always agrees with the timetable that was recorded.

## Transport routes: origin and destination rules

A transport option must start and end in different places: an origin that
matches its destination, ignoring capital letters, is rejected as not being a
journey. Car rental is the exception, because collecting and returning a hire
car at the same depot is normal. An edit is checked against the whole updated
record, so changing only the destination cannot turn an option into a
journey that goes nowhere.
