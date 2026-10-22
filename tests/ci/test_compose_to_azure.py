"""Tests for the compose -> Azure Container Apps renderer."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "deploy" / "azure" / "compose_to_azure.py"
DOMAIN = "env.example.io"
PULL_IDENTITY = (
    "/subscriptions/s/resourceGroups/rg"
    "/providers/Microsoft.ManagedIdentity/userAssignedIdentities/pull"
)


def load():
    spec = importlib.util.spec_from_file_location("compose_to_azure", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CONFIG = {
    "services": {
        "student-1": {"image": "alpine:3"},
        "shared-ui": {
            "build": {},
            "ports": [{"target": 80, "published": "8080"}],
            "environment": {"STUDENT1_UI_URL": "http://localhost:8081"},
        },
        "student-1-frontend": {
            "build": {},
            "ports": [{"target": 8081, "published": "8081"}],
            "depends_on": {"student-1-backend": {}},
            "environment": {
                "STUDENT1_FRONTEND_BACKEND_BASE_URL": "http://student-1-backend:8001",
                "TRIPGENIE_PORTAL_URL": "http://localhost:8080",
                "BLANK": "",
            },
        },
        "student-1-database": {
            "build": {},
            "expose": ["8002"],
            "volumes": [{"target": "/data"}],
        },
    }
}


def rendered_apps():
    result = load().apps(json.loads(json.dumps(CONFIG)), "r.io", "abc", DOMAIN)
    return {a["name"]: a for a in result}


def az_args(name):
    return load().az_args(rendered_apps()[name], "env", "r.io", PULL_IDENTITY, "0")


def test_apps_pull_with_the_given_identity_not_a_system_one():
    # `--registry-identity system` makes the CLI deploy a placeholder image first.
    args = az_args("student-1-frontend")
    assert args[args.index("--registry-identity") + 1] == PULL_IDENTITY
    assert args[args.index("--image") + 1] == "r.io/tripgenie-student-1-frontend:abc"


def test_only_built_services_are_deployed():
    assert set(rendered_apps()) == {
        "shared-ui",
        "student-1-frontend",
        "student-1-database",
    }


def test_browser_urls_become_cloud_addresses_and_service_urls_stay():
    apps = rendered_apps()
    assert apps["shared-ui"]["env"] == {
        "STUDENT1_UI_URL": f"https://student-1-frontend.{DOMAIN}"
    }
    # Internal apps keep their compose port, so service URLs pass through, and a
    # blank value is dropped so the code default applies.
    assert apps["student-1-frontend"]["env"] == {
        "STUDENT1_FRONTEND_BACKEND_BASE_URL": "http://student-1-backend:8001",
        "TRIPGENIE_PORTAL_URL": f"https://shared-ui.{DOMAIN}",
    }


def test_frontends_get_public_https_ingress():
    args = az_args("student-1-frontend")
    assert args[args.index("--ingress") + 1] == "external"
    assert args[args.index("--target-port") + 1] == "8081"
    assert "--transport" not in args
    assert args[args.index("--min-replicas") + 1] == "0"
    assert "TRIPGENIE_PORTAL_URL=https://shared-ui.env.example.io" in args


def test_backends_and_databases_get_internal_tcp_on_their_compose_port():
    args = az_args("student-1-database")
    assert args[args.index("--ingress") + 1] == "internal"
    assert args[args.index("--transport") + 1] == "tcp"
    assert args[args.index("--target-port") + 1] == "8002"
    assert args[args.index("--exposed-port") + 1] == "8002"
    assert args[args.index("--min-replicas") + 1] == "1"
    assert "--env-vars" not in args


def test_images_are_amd64_registry_builds_without_grouping_links():
    services = load().images(json.loads(json.dumps(CONFIG)), "r.io", "abc")["services"]
    frontend = services["student-1-frontend"]
    assert frontend["image"] == "r.io/tripgenie-student-1-frontend:abc"
    assert frontend["platform"] == "linux/amd64"
    assert "depends_on" not in frontend
    assert "student-1" not in services


def test_renders_the_real_compose_file():
    config = compose_config()
    apps = load().apps(config, "r.io", "abc", DOMAIN)
    assert len(apps) == 18
    assert sum(a["external"] for a in apps) == 6
    # The image build file must itself be a valid compose project.
    images = load().images(config, "r.io", "abc")
    assert set(images["volumes"]) >= {"student-1-db", "student-5-sqlite"}


def compose_config(*env_file):
    compose = ["docker", "compose", "-f", str(ROOT / "docker-compose.yml")]
    for name in env_file:
        compose += ["--env-file", str(ROOT / "shared" / "configuration" / name)]
    config = subprocess.run(  # noqa: S603 - fixed argv, no user input
        [*compose, "config", "--format", "json"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return json.loads(config)


def test_cloud_student_1_backend_gets_no_ai_mode_url_and_locals_keep_it():
    # Blank in .env.cloud must survive compose (no ":-" fallback) and then be
    # dropped here, leaving the backend's default: AI-Mode not configured.
    apps = {
        a["name"]: a
        for a in load().apps(compose_config(".env.cloud"), "r.io", "abc", DOMAIN)
    }
    backend_env = apps["student-1-backend"]["env"]
    assert "STUDENT1_BACKEND_AI_MODE_BASE_URL" not in backend_env
    assert backend_env["STUDENT1_BACKEND_RAG_ENABLED"] == "false"
    assert backend_env["STUDENT1_BACKEND_MCP_ENABLED"] == "false"
    for local in ((), (".env.example",)):
        environment = compose_config(*local)["services"]["student-1-backend"][
            "environment"
        ]
        assert (
            environment["STUDENT1_BACKEND_AI_MODE_BASE_URL"]
            == "http://host.docker.internal:8006"
        )


def test_only_public_ports_map_to_cloud_addresses():
    config = json.loads(json.dumps(CONFIG))
    config["services"]["student-1-backend"] = {
        "build": {},
        "ports": [{"target": 8001, "published": "18001", "host_ip": "127.0.0.1"}],
    }
    config["services"]["student-1-frontend"]["environment"] = {
        "AI_URL": "http://localhost:8006",
        "BACKEND_DEBUG_URL": "http://localhost:18001",
    }
    apps = {a["name"]: a for a in load().apps(config, "r.io", "abc", DOMAIN)}
    # Unknown or internal-only ports stay as they are rather than crash the
    # render or point a browser at an app it can never reach.
    assert apps["student-1-frontend"]["env"] == {
        "AI_URL": "http://localhost:8006",
        "BACKEND_DEBUG_URL": "http://localhost:18001",
    }
