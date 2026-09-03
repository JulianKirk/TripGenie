from __future__ import annotations

from threading import Barrier

import httpx
from backend_service.activity_client import ActivityClient
from backend_service.config import Settings

ACTIVITY_IDS = [
    "11111111-1111-1111-1111-111111111111",
    "22222222-2222-2222-2222-222222222222",
]


def test_activity_enrichment_fetches_independent_records_concurrently() -> None:
    rendezvous = Barrier(2, timeout=5)

    def handler(request: httpx.Request) -> httpx.Response:
        activity_id = request.url.path.rsplit("/", 1)[-1]
        rendezvous.wait()
        return httpx.Response(
            200,
            json={
                "id": activity_id,
                "name": f"Activity {activity_id[0]}",
                "price": "10.00",
                "pricing_basis": "PER_PERSON",
                "duration_minutes": 60,
            },
        )

    settings = Settings(database_api_base_url="http://database.test")
    client = ActivityClient(settings, transport=httpx.MockTransport(handler))
    try:
        found = client.details(ACTIVITY_IDS)
    finally:
        client.close()

    assert list(found) == ACTIVITY_IDS
