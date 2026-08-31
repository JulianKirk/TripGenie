from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REQUIRED_SERVICES = (
    "shared-ui",
    "student-1-frontend",
    "student-1-backend",
    "student-1-database",
    "student-2-service",
    "student-3-service",
    "student-4-service",
    "student-5-service",
    "ai-mode",
)
INTERNAL_ONLY_SERVICES = ("student-1-backend", "student-1-database", "ai-mode")
BUILD_REQUIRED_SERVICES = (
    "shared-ui",
    "student-1-frontend",
    "student-1-backend",
    "student-1-database",
    "ai-mode",
)
ENV_EXAMPLE_PATH = Path("shared/configuration/.env.example")
SHARED_PORTAL_PATH = Path("shared/frontend/index.html")
README_PATH = Path("README.md")


def _fail(message: str) -> None:
    details = f"Compose validation failed: {message}"
    raise SystemExit(details)


def _ensure(condition: bool, message: str) -> None:
    if not condition:
        _fail(message)


def _require_mapping(value: Any, *, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail(f"expected '{field_name}' to be a JSON object")
    return value


def _load_json(path_argument: str) -> dict[str, Any]:
    payload = Path(path_argument).read_text(encoding="utf-8")
    try:
        loaded = json.loads(payload)
    except json.JSONDecodeError as exc:
        _fail(f"unable to parse JSON from {path_argument}: {exc}")
    return _require_mapping(loaded, field_name="compose config")


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        _fail(f"required file is missing: {path.as_posix()}")
    return ""


def _normalise_environment(raw_environment: Any) -> dict[str, str]:
    if raw_environment is None:
        return {}

    if isinstance(raw_environment, dict):
        return {
            str(key): "" if value is None else str(value)
            for key, value in raw_environment.items()
        }

    if isinstance(raw_environment, list):
        resolved: dict[str, str] = {}
        for item in raw_environment:
            if not isinstance(item, str) or "=" not in item:
                _fail("service environment entries must be KEY=VALUE strings")
            key, value = item.split("=", 1)
            resolved[key] = value
        return resolved

    _fail("service environment must be a JSON object or array")
    return {}


def _normalise_ports(raw_ports: Any) -> list[str]:
    if raw_ports in (None, []):
        return []

    if not isinstance(raw_ports, list):
        _fail("service ports must be an array")

    resolved: list[str] = []
    for item in raw_ports:
        if isinstance(item, str):
            resolved.append(item)
            continue

        if not isinstance(item, dict):
            _fail("service ports entries must be strings or objects")

        published = item.get("published")
        target = item.get("target")
        if published is None or target is None:
            continue

        host_ip = item.get("host_ip")
        port_mapping = f"{published}:{target}"
        if host_ip:
            port_mapping = f"{host_ip}:{port_mapping}"
        resolved.append(port_mapping)

    return resolved


def _has_port_mapping(
    raw_ports: Any,
    *,
    published: str,
    target: str,
) -> bool:
    expected = f"{published}:{target}"
    for port_mapping in _normalise_ports(raw_ports):
        normalized = port_mapping.rsplit("/", 1)[0]
        if normalized == expected or normalized.endswith(f":{expected}"):
            return True
    return False


def _normalise_volume_targets(raw_volumes: Any) -> dict[str, str]:
    if raw_volumes in (None, []):
        return {}

    if not isinstance(raw_volumes, list):
        _fail("service volumes must be an array")

    resolved: dict[str, str] = {}
    for item in raw_volumes:
        if isinstance(item, str):
            parts = item.split(":", 2)
            if len(parts) >= 2:
                resolved[parts[1]] = parts[0]
            continue

        if not isinstance(item, dict):
            _fail("service volumes entries must be strings or objects")

        if item.get("type") != "volume":
            continue

        source = item.get("source")
        target = item.get("target")
        if source is None or target is None:
            continue
        resolved[str(target)] = str(source)

    return resolved


def _normalise_extra_hosts(raw_extra_hosts: Any) -> list[str]:
    if raw_extra_hosts in (None, []):
        return []

    if not isinstance(raw_extra_hosts, list):
        _fail("service extra_hosts must be an array")

    resolved: list[str] = []
    for item in raw_extra_hosts:
        if not isinstance(item, str):
            _fail("service extra_hosts entries must be strings")
        resolved.append(item)
    return resolved


def _has_extra_host(
    raw_extra_hosts: Any,
    expected_host: str,
    expected_value: str,
) -> bool:
    expected_pairs = {
        f"{expected_host}:{expected_value}",
        f"{expected_host}={expected_value}",
    }
    normalized = _normalise_extra_hosts(raw_extra_hosts)
    return any(host_entry in expected_pairs for host_entry in normalized)


def _has_build_definition(service: dict[str, Any]) -> bool:
    build = service.get("build")
    return isinstance(build, (dict, str))


def _depends_on_condition(service: dict[str, Any], dependency_name: str) -> str | None:
    depends_on = service.get("depends_on")
    if depends_on is None:
        return None

    if isinstance(depends_on, list):
        return "service_started" if dependency_name in depends_on else None

    if not isinstance(depends_on, dict):
        _fail("service depends_on must be an array or object")

    dependency = depends_on.get(dependency_name)
    if dependency is None:
        return None
    if dependency is True:
        return "service_started"
    if not isinstance(dependency, dict):
        _fail("depends_on conditions must be objects")
    return str(dependency.get("condition", "service_started"))


def _healthcheck_command(service: dict[str, Any]) -> str:
    healthcheck = service.get("healthcheck")
    if healthcheck is None:
        return ""
    if not isinstance(healthcheck, dict):
        _fail("service healthcheck must be an object")

    test = healthcheck.get("test")
    if isinstance(test, str):
        return test
    if isinstance(test, list):
        return " ".join(str(part) for part in test)
    _fail("service healthcheck.test must be a string or array")
    return ""


def _validate_networks(config: dict[str, Any], services: dict[str, Any]) -> None:
    networks = _require_mapping(config.get("networks", {}), field_name="networks")
    _ensure(networks, "no networks were resolved by docker compose config")
    _ensure(
        "default" in networks,
        "the shared Compose default network was not resolved",
    )

    for service_name in REQUIRED_SERVICES:
        service = _require_mapping(
            services[service_name],
            field_name=f"services.{service_name}",
        )
        if service.get("network_mode"):
            continue

        attached_networks = service.get("networks")
        if attached_networks is None:
            continue
        if isinstance(attached_networks, list):
            _ensure(
                len(attached_networks) > 0,
                f"{service_name} is not attached to any Compose network",
            )
            continue
        if isinstance(attached_networks, dict):
            _ensure(
                len(attached_networks) > 0,
                f"{service_name} is not attached to any Compose network",
            )
            continue
        _fail(f"{service_name} networks must be an array or object")


def main() -> int:
    if len(sys.argv) != 2:
        _fail("usage: python scripts/test/validate_compose_config.py <compose.json>")

    config = _load_json(sys.argv[1])
    services = _require_mapping(config.get("services"), field_name="services")
    volumes = _require_mapping(config.get("volumes", {}), field_name="volumes")
    env_example_text = _read_text(ENV_EXAMPLE_PATH)
    shared_portal_html = _read_text(SHARED_PORTAL_PATH)
    root_readme = _read_text(README_PATH)

    missing_services = [
        service_name
        for service_name in REQUIRED_SERVICES
        if service_name not in services
    ]
    _ensure(
        not missing_services,
        f"missing required services: {', '.join(sorted(missing_services))}",
    )
    _ensure(
        "STUDENT1_FRONTEND_HOST_PORT" not in env_example_text,
        "shared/configuration/.env.example must not define STUDENT1_FRONTEND_HOST_PORT",
    )
    _ensure(
        "http://localhost:8081" in shared_portal_html,
        "shared/frontend/index.html must keep the Student 1 localhost:8081 route",
    )
    _ensure(
        "exec ollama" not in root_readme,
        "README must not document docker compose exec ollama bootstrap steps",
    )

    _validate_networks(config, services)
    _ensure("student-1-sqlite" in volumes, "student-1-sqlite volume is missing")
    _ensure("ollama-models" not in volumes, "ollama-models volume must not exist")
    _ensure("ollama" not in services, "ollama service must not exist")
    _ensure(
        "ollama-bootstrap" not in services
        and "model-bootstrap" not in services
        and "model-pull" not in services,
        "model bootstrap/pull services must not exist",
    )

    shared_ui = _require_mapping(services["shared-ui"], field_name="services.shared-ui")
    frontend = _require_mapping(
        services["student-1-frontend"],
        field_name="services.student-1-frontend",
    )
    backend = _require_mapping(
        services["student-1-backend"],
        field_name="services.student-1-backend",
    )
    database = _require_mapping(
        services["student-1-database"],
        field_name="services.student-1-database",
    )
    ai_mode = _require_mapping(services["ai-mode"], field_name="services.ai-mode")

    for service_name in BUILD_REQUIRED_SERVICES:
        _ensure(
            _has_build_definition(
                _require_mapping(
                    services[service_name],
                    field_name=f"services.{service_name}",
                )
            ),
            f"{service_name} must keep a Compose build definition",
        )

    _ensure(
        _has_port_mapping(shared_ui.get("ports"), published="8080", target="80"),
        "shared-ui must publish host port 8080 to container port 80",
    )
    _ensure(
        _has_port_mapping(
            frontend.get("ports"),
            published="8081",
            target="8081",
        ),
        "student-1-frontend must publish host port 8081",
    )

    for service_name in INTERNAL_ONLY_SERVICES:
        _ensure(
            not _normalise_ports(services[service_name].get("ports")),
            f"{service_name} must stay internal-only and not publish host ports",
        )

    frontend_env = _normalise_environment(frontend.get("environment"))
    backend_env = _normalise_environment(backend.get("environment"))
    database_env = _normalise_environment(database.get("environment"))
    ai_mode_env = _normalise_environment(ai_mode.get("environment"))

    _ensure(
        frontend_env.get("STUDENT1_FRONTEND_BACKEND_BASE_URL")
        == "http://student-1-backend:8001",
        "student-1-frontend must target http://student-1-backend:8001",
    )
    _ensure(
        backend_env.get("STUDENT1_BACKEND_DB_API_BASE_URL")
        == "http://student-1-database:8002",
        "student-1-backend must target http://student-1-database:8002",
    )
    _ensure(
        backend_env.get("STUDENT1_BACKEND_AI_MODE_BASE_URL")
        == "http://ai-mode:8006",
        "student-1-backend must target http://ai-mode:8006",
    )
    _ensure(
        ai_mode_env.get("AI_MODE_OLLAMA_BASE_URL")
        == "http://host.docker.internal:11434",
        "ai-mode must target http://host.docker.internal:11434",
    )
    _ensure(
        ai_mode_env.get("AI_MODE_DEFAULT_MODEL") == "qwen2.5:0.5b",
        "ai-mode must default to qwen2.5:0.5b",
    )
    _ensure(
        _has_extra_host(
            ai_mode.get("extra_hosts"),
            "host.docker.internal",
            "host-gateway",
        ),
        "ai-mode must define host.docker.internal host-gateway mapping",
    )

    for prohibited_variable in (
        "OLLAMA_HOST",
        "OLLAMA_URL",
        "AI_MODE_OLLAMA_BASE_URL",
    ):
        _ensure(
            prohibited_variable not in backend_env,
            "student-1-backend must not receive direct Ollama config "
            f"({prohibited_variable})",
        )

    _ensure(
        "AI_MODE_OLLAMA_BASE_URL" not in frontend_env,
        "student-1-frontend must not receive direct Ollama config",
    )
    _ensure(
        "AI_MODE_OLLAMA_BASE_URL" not in database_env,
        "student-1-database must not receive direct Ollama config",
    )

    _ensure(
        _depends_on_condition(frontend, "student-1-backend") == "service_healthy",
        "student-1-frontend must wait for student-1-backend health",
    )
    _ensure(
        _depends_on_condition(backend, "student-1-database") == "service_healthy",
        "student-1-backend must wait for student-1-database health",
    )
    _ensure(
        _depends_on_condition(backend, "ai-mode") is None,
        "student-1-backend must not depend on ai-mode for startup",
    )
    _ensure(
        ai_mode.get("depends_on") in (None, {}, []),
        "ai-mode must not depend on an Ollama container",
    )

    _ensure(
        "/ready" in _healthcheck_command(frontend),
        "student-1-frontend healthcheck must probe /ready",
    )
    _ensure(
        "/ready" in _healthcheck_command(backend),
        "student-1-backend healthcheck must probe /ready",
    )
    _ensure(
        "/internal/health" in _healthcheck_command(database),
        "student-1-database healthcheck must probe /internal/health",
    )
    _ensure(
        "/ready" in _healthcheck_command(ai_mode),
        "ai-mode healthcheck must probe /ready",
    )

    database_volumes = _normalise_volume_targets(database.get("volumes"))
    _ensure(
        database_volumes.get("/data/student-1") == "student-1-sqlite",
        "student-1-database must mount the student-1-sqlite volume at /data/student-1",
    )

    print("Compose config validation passed for Student 1 Release 0 smoke CI.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
