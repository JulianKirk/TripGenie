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


def test_ai_mode_is_containerised_and_connects_to_host_mcp() -> None:
    services = compose_services()
    assert not {"mcp-server", "rag-server", "agentic-loop"} & services.keys()
    ai_mode = services["ai-mode"]
    assert ai_mode["environment"]["AI_MODE_MCP_URL"] == (
        "http://host.docker.internal:8012/mcp"
    )
    assert ai_mode["environment"]["AI_MODE_OLLAMA_BASE_URL"] == (
        "http://host.docker.internal:11434"
    )
    assert "host.docker.internal=host-gateway" in ai_mode["extra_hosts"]
    assert ai_mode["ports"][0]["host_ip"] == "127.0.0.1"
    for student, variable in (
        (1, "STUDENT1_BACKEND_AI_MODE_BASE_URL"),
        (2, "AI_MODE_URL"),
        (3, "STUDENT3_BACKEND_AI_MODE_BASE_URL"),
        (4, "AI_MODE_URL"),
        (5, "STUDENT5_BACKEND_AI_MODE_BASE_URL"),
    ):
        backend = services[f"student-{student}-backend"]
        assert backend["environment"][variable] == "http://ai-mode:8006"
    backend = services["student-4-backend"]
    assert "MCP_URL" not in backend["environment"]
    assert backend["environment"]["AI_ASSISTANT_ENABLED"] == "true"
    assert backend["depends_on"]["ai-mode"]["condition"] == "service_started"


def test_agentic_overlay_preserves_single_activity_backend_binding() -> None:
    services = compose_services(agentic=True)
    ports = services["student-4-backend"]["ports"]
    assert len(ports) == 1
    assert ports[0]["host_ip"] == "127.0.0.1"
    assert ports[0]["published"] == "18008"
