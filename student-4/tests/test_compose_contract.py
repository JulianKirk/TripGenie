from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, cast


def compose_services(*, agentic: bool = False) -> dict[str, dict[str, Any]]:
    repository = Path(__file__).resolve().parents[2]
    command = ["docker", "compose", "-f", "docker-compose.yml"]
    if agentic:
        command += ["-f", "ai-services/agentic-loop/docker-compose.agentic.yml"]
    result = subprocess.run(
        [*command, "config", "--format", "json"],
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


def test_student_4_publishes_public_backend_for_host_mcp() -> None:
    services = compose_services()

    assert services["student-4-backend"]["expose"] == ["8008"]
    backend_port = services["student-4-backend"]["ports"][0]
    assert backend_port["host_ip"] == "127.0.0.1"
    assert backend_port["published"] == "18008"
    assert backend_port["target"] == 8008
    assert "ports" not in services["student-4-database"]
    assert "ports" not in services["student-4"]
    frontend_port = services["student-4-frontend"]["ports"][0]
    assert frontend_port["target"] == 8084
    assert frontend_port["published"] == "8084"
    assert frontend_port["protocol"] == "tcp"


def test_host_ai_services_stay_out_of_compose() -> None:
    services = compose_services()
    host_only = ("ai-mode", "mcp", "rag", "ollama", "agentic")
    assert not [name for name in services if any(h in name for h in host_only)]
    for student, variable in (
        (1, "STUDENT1_BACKEND_AI_MODE_BASE_URL"),
        (2, "AI_MODE_URL"),
        (3, "STUDENT3_BACKEND_AI_MODE_BASE_URL"),
        (4, "AI_MODE_URL"),
        (5, "STUDENT5_BACKEND_AI_MODE_BASE_URL"),
    ):
        backend = services[f"student-{student}-backend"]
        assert backend["environment"][variable] == "http://host.docker.internal:8006"
        assert "host.docker.internal=host-gateway" in backend["extra_hosts"]
    # Host MCP reaches the Student 3 transport tools here.
    transport_port = services["student-3-backend"]["ports"][0]
    assert (transport_port["host_ip"], transport_port["published"]) == (
        "127.0.0.1",
        "18003",
    )
    backend = services["student-4-backend"]
    assert "MCP_URL" not in backend["environment"]
    assert backend["environment"]["AI_ASSISTANT_ENABLED"] == "true"


def test_student_4_backend_reaches_host_rag() -> None:
    environment = compose_services()["student-4-backend"]["environment"]

    assert environment["RAG_URL"] == "http://host.docker.internal:8011"
    assert environment["RAG_ENABLED"] == "true"
    assert float(environment["RAG_TIMEOUT"]) > 0


def test_agentic_overlay_preserves_single_activity_backend_binding() -> None:
    services = compose_services(agentic=True)
    ports = services["student-4-backend"]["ports"]
    assert len(ports) == 1
    assert ports[0]["host_ip"] == "127.0.0.1"
    assert ports[0]["published"] == "18008"
