from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, cast


def compose_services(*, agentic: bool = False) -> dict[str, dict[str, Any]]:
    repository = Path(__file__).resolve().parents[2]
    command = ["docker", "compose", "-f", "docker-compose.yml"]
    if agentic:
        command += ["-f", "ai-services/agentic-loop/docker-compose.agentic.yml"]
    result = subprocess.run(  # noqa: S603 - fixed Docker command assembled above
        [*command, "config", "--format", "json"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    config = cast("dict[str, Any]", json.loads(result.stdout))
    return cast("dict[str, dict[str, Any]]", config["services"])


def test_student_4_compose_target_waits_for_healthy_frontend() -> None:
    services = compose_services()

    frontend_dependency = services["student-4"]["depends_on"]["student-4-frontend"]
    assert frontend_dependency["condition"] == "service_healthy"
    assert frontend_dependency["required"] is True


def test_student_4_compose_slice_preserves_dependency_boundaries() -> None:
    services = compose_services()

    database_dependency = services["student-4-backend"]["depends_on"][
        "student-4-database"
    ]
    assert database_dependency["condition"] == "service_healthy"
    assert database_dependency["required"] is True
    backend_dependency = services["student-4-frontend"]["depends_on"][
        "student-4-backend"
    ]
    assert set(services["student-4-frontend"]["depends_on"]) == {"student-4-backend"}
    assert backend_dependency["condition"] == "service_healthy"
    assert backend_dependency["required"] is True


def test_student_4_publishes_public_backend_for_host_mcp() -> None:
    services = compose_services()

    backend_ports = services["student-4-backend"]["ports"]
    assert backend_ports
    assert all(port["host_ip"] == "127.0.0.1" for port in backend_ports)
    assert "ports" not in services["student-4-database"]
    assert "ports" not in services["student-4"]
    assert services["student-4-frontend"]["ports"]


def test_host_ai_services_stay_out_of_compose() -> None:
    services = compose_services()
    host_only = ("ai-mode", "mcp", "rag", "ollama", "agentic", "multi-agent")
    assert not [name for name in services if any(h in name for h in host_only)]
    assert (
        "host.docker.internal=host-gateway"
        in services["student-4-backend"]["extra_hosts"]
    )


def test_agentic_overlay_preserves_single_activity_backend_binding() -> None:
    base = compose_services()["student-4-backend"]["ports"]
    overlaid = compose_services(agentic=True)["student-4-backend"]["ports"]

    assert len(base) == 1
    assert overlaid == base
