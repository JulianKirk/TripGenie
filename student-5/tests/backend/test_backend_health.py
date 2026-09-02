import httpx
from fastapi.testclient import TestClient
from student5_backend_service.app import create_app
from student5_backend_service.config import Settings


def test_backend_health_and_readiness() -> None:
    database = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"data": {"status": "ready"}})
    )
    settings = Settings(database_api_base_url="http://database.test")

    with TestClient(create_app(settings, database_transport=database)) as client:
        assert client.get("/health").json() == {
            "data": {
                "status": "healthy",
                "service": "student-5-backend",
                "dependencies": {"database": True},
            }
        }
        assert client.get("/ready").json() == {
            "data": {
                "status": "ready",
                "service": "student-5-backend",
                "dependencies": {"database": True},
            }
        }
