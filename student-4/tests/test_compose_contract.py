from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, cast


def compose_services() -> dict[str, dict[str, Any]]:
    repository = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        ["docker", "compose", "config", "--format", "json"],
        cwd=repository,
        check=True,
        capture_output=True,
        env={**os.environ, "STUDENT4_FRONTEND_HOST_PORT": "8084"},
        text=True,
    )
    config = cast("dict[str, Any]", json.loads(result.stdout))
    return cast("dict[str, dict[str, Any]]", config["services"])


def test_student_4_compose_target_starts_the_healthy_frontend() -> None:
    services = compose_services()

    assert "student-4-service" not in services
    frontend_dependency = services["student-4"]["depends_on"]["student-4-frontend"]
    assert frontend_dependency["condition"] == "service_healthy"
    assert frontend_dependency["required"] is True


def test_student_4_compose_slice_is_health_gated() -> None:
    services = compose_services()

    database_dependency = services["student-4-backend"]["depends_on"][
        "student-4-database"
    ]
    assert database_dependency["condition"] == "service_healthy"
    assert database_dependency["required"] is True
    backend_dependency = services["student-4-frontend"]["depends_on"][
        "student-4-backend"
    ]
    assert backend_dependency["condition"] == "service_healthy"
    assert backend_dependency["required"] is True
    assert services["student-4-frontend"]["healthcheck"]["test"][-1].endswith(
        "http://127.0.0.1:8084/ready', timeout=3)"
    )


def test_student_4_publishes_only_its_frontend() -> None:
    services = compose_services()

    assert services["student-4-backend"]["expose"] == ["8008"]
    assert "ports" not in services["student-4-backend"]
    assert "ports" not in services["student-4-database"]
    assert "ports" not in services["student-4"]
    frontend_port = services["student-4-frontend"]["ports"][0]
    assert frontend_port["target"] == 8084
    assert frontend_port["published"] == "8084"
    assert frontend_port["protocol"] == "tcp"
