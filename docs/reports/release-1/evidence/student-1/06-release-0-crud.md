# Release 0 regression: Student 1 backend CRUD and database operations

Captured 2026-10-02T02:49:49Z (UTC) against the Compose student-1-backend (published at 127.0.0.1:18001), main aec615c.
Expected: list/read succeed; an itinerary item can be created, read, updated and deleted through the public API (persisted by student-1-database); seed data is unchanged afterwards.

```
$ curl -s http://127.0.0.1:18001/api/trips | jq '.data | length'
10
$ curl -s http://127.0.0.1:18001/api/trips/trip_2026_melbourne_food_trail | jq '.data | {id,name,destination,start_date,end_date,status}'
{"id": "trip_2026_melbourne_food_trail", "name": "Melbourne Food Trail", "destination": "Melbourne", "start_date": "2026-11-12", "end_date": "2026-11-16", "status": "draft"}
$ curl -s -X GET http://127.0.0.1:18001/api/trips/trip_2026_melbourne_food_trail/itinerary-items 
{"data":[{"date":"2026-11-13","start_time":"12:00","end_time":"14:00","title":"Market Lunch","location":"Queen Victoria Market","description":"Sample local produce and casual lunch stalls.","category":"meal","notes":"Arrive hungry.","id":"item_2026_melbourne_market_lunch","trip_id":"trip_2026_melbourne_food_trail"}]}
[HTTP 200, 0.011402s]

$ curl -s -X POST http://127.0.0.1:18001/api/trips/trip_2026_melbourne_food_trail/itinerary-items -d '{"id":"item_r1_evidence_crud","date":"2026-11-14","start_time":"09:00","end_time":"10:00","title":"R1 evidence breakfast","location":"Degraves Street","category":"meal","notes":"Temporary evidence record"}'
{"data":{"date":"2026-11-14","start_time":"09:00","end_time":"10:00","title":"R1 evidence breakfast","location":"Degraves Street","description":null,"category":"meal","notes":"Temporary evidence record","id":"item_r1_evidence_crud","trip_id":"trip_2026_melbourne_food_trail"}}
[HTTP 201, 0.057540s]

$ curl -s -X GET http://127.0.0.1:18001/api/itinerary-items/item_r1_evidence_crud 
{"data":{"date":"2026-11-14","start_time":"09:00","end_time":"10:00","title":"R1 evidence breakfast","location":"Degraves Street","description":null,"category":"meal","notes":"Temporary evidence record","id":"item_r1_evidence_crud","trip_id":"trip_2026_melbourne_food_trail"}}
[HTTP 200, 0.007853s]

$ curl -s -X PATCH http://127.0.0.1:18001/api/itinerary-items/item_r1_evidence_crud -d '{"title":"R1 evidence breakfast (updated)","end_time":"10:30"}'
{"data":{"date":"2026-11-14","start_time":"09:00","end_time":"10:30","title":"R1 evidence breakfast (updated)","location":"Degraves Street","description":null,"category":"meal","notes":"Temporary evidence record","id":"item_r1_evidence_crud","trip_id":"trip_2026_melbourne_food_trail"}}
[HTTP 200, 0.018464s]

$ curl -s -X DELETE http://127.0.0.1:18001/api/itinerary-items/item_r1_evidence_crud 
{"data":{"id":"item_r1_evidence_crud","deleted":true}}
[HTTP 200, 0.013884s]

$ curl -s -X GET http://127.0.0.1:18001/api/itinerary-items/item_r1_evidence_crud 
{"error":{"code":"NOT_FOUND","message":"Itinerary item 'item_r1_evidence_crud' was not found.","details":[{"field":"id","issue":"resource does not exist"}]}}
[HTTP 404, 0.023049s]

$ curl -s http://127.0.0.1:18001/api/trips/trip_2026_melbourne_food_trail/itinerary-items | jq '[.data[].id]'
['item_2026_melbourne_market_lunch']
```
