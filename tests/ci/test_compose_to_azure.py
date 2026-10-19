"""Tests for the compose -> Azure Container Apps renderer."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "deploy" / "azure" / "compose_to_azure.py"
DOMAIN = "__DOMAIN__"


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
    result = load().apps(json.loads(json.dumps(CONFIG)), "r.io", "abc")
    return {a["name"]: a for a in result["parameters"]["apps"]["value"]}


def test_only_built_services_are_deployed():
    assert set(rendered_apps()) == {
        "shared-ui",
        "student-1-frontend",
        "student-1-database",
    }


def test_browser_urls_become_cloud_addresses_and_service_urls_stay():
    apps = rendered_apps()
    assert apps["shared-ui"]["env"] == [
        {"name": "STUDENT1_UI_URL", "value": f"https://student-1-frontend.{DOMAIN}"}
    ]
    frontend = {e["name"]: e["value"] for e in apps["student-1-frontend"]["env"]}
    # Internal apps keep their compose port, so service URLs pass through, and a
    # blank value is dropped so the code default applies.
    assert frontend == {
        "STUDENT1_FRONTEND_BACKEND_BASE_URL": "http://student-1-backend:8001",
        "TRIPGENIE_PORTAL_URL": f"https://shared-ui.{DOMAIN}",
    }


def test_ingress_and_storage_follow_the_service_kind():
    apps = rendered_apps()
    frontend, database = apps["student-1-frontend"], apps["student-1-database"]
    assert frontend["external"]
    assert frontend["port"] == 8081
    assert not frontend["volumePath"]
    assert not database["external"]
    assert database["port"] == 8002
    assert database["volumePath"] == "/data"


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
    apps = load().apps(json.loads(config), "r.io", "abc")["parameters"]["apps"]["value"]
    assert len(apps) == 18
    assert sum(a["external"] for a in apps) == 6
    # The image build file must itself be a valid compose project.
    images = load().images(json.loads(config), "r.io", "abc")
    assert set(images["volumes"]) >= {"student-1-db", "student-5-sqlite"}
