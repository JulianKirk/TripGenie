from fastapi.testclient import TestClient
from student5_frontend_service.app import create_app


def test_frontend_health_and_readiness() -> None:
    client = TestClient(create_app())

    assert client.get("/health").json() == {
        "data": {"status": "healthy", "service": "student-5-frontend"}
    }
    assert client.get("/ready").json() == {
        "data": {"status": "ready", "service": "student-5-frontend"}
    }