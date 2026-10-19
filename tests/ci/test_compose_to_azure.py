"""Tests for the compose -> Azure Container Apps renderer."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "deploy" / "azure" / "compose_to_azure.py"
DOMAIN = "env.example.io"


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
    return load().az_args(rendered_apps()[name], "env", "r.io", "0")


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
    compose = ["docker", "compose", "-f", str(ROOT / "docker-compose.yml")]
    config = subprocess.run(  # noqa: S603 - fixed argv, no user input
        [*compose, "config", "--format", "json"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    apps = load().apps(json.loads(config), "r.io", "abc", DOMAIN)
    assert len(apps) == 18
    assert sum(a["external"] for a in apps) == 6
    # The image build file must itself be a valid compose project.
    images = load().images(json.loads(config), "r.io", "abc")
    assert set(images["volumes"]) >= {"student-1-db", "student-5-sqlite"}
