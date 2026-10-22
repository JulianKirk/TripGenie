"""Cloud endpoint and data security: configuration and the checks that prove it."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AZURE = ROOT / "scripts" / "deploy" / "azure"
DOMAIN = "env.example.io"
PULL_IDENTITY = "/subscriptions/s/resourceGroups/rg/providers/x/tripgenie-acr-pull"


def load(name):
    spec = importlib.util.spec_from_file_location(name, AZURE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


smoke_test = load("smoke_test")
security_check = load("security_check")
HEADERS = smoke_test.SECURITY_HEADERS


def compose_services(*env_file):
    command = ["docker", "compose", "-f", str(ROOT / "docker-compose.yml")]
    for name in env_file:
        command += ["--env-file", str(ROOT / "shared" / "configuration" / name)]
    config = subprocess.run(  # noqa: S603 - fixed argv, no user input
        [*command, "config", "--format", "json"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return json.loads(config)["services"]


def test_every_uvicorn_frontend_sends_the_security_headers_locally_and_in_the_cloud():
    expected = " ".join(f"{k}:{v}" for k, v in HEADERS.items())
    for profile in [(), (".env.cloud",)]:
        services = compose_services(*profile)
        sending = {
            name: s["environment"]
            for name, s in services.items()
            if "UVICORN_HEADERS" in (s.get("environment") or {})
        }
        assert set(sending) == {f"student-{n}-frontend" for n in range(1, 6)}
        for env in sending.values():
            assert env["UVICORN_HEADERS"] == expected
            assert env["UVICORN_SERVER_HEADER"] == "false"


def test_the_portal_sends_the_same_headers_and_hides_its_version():
    template = (ROOT / "shared" / "frontend" / "default.conf.template").read_text()
    assert "server_tokens off;" in template
    for name, value in HEADERS.items():
        assert f'add_header {name} "{value}" always;' in template


def test_the_registry_is_created_without_an_admin_user():
    assert "--admin-enabled false" in (AZURE / "build-images.sh").read_text()


def fake_endpoints(monkeypatch, responses):
    monkeypatch.setattr(
        smoke_test, "headers_of", lambda url: responses.get(url, (404, {}))
    )


def secure(**extra):
    return (200, {**HEADERS, **extra})


def test_secure_https_frontends_pass_every_check(monkeypatch):
    url = f"https://student-5-frontend.{DOMAIN}"
    fake_endpoints(
        monkeypatch,
        {
            url: secure(),
            f"http://student-5-frontend.{DOMAIN}": (301, {"Location": url + "/"}),
        },
    )
    results = list(smoke_test.security_checks([url]))
    assert [name for name, ok, _ in results if not ok] == []
    assert {name for name, _, _ in results} >= {
        f"Not public: student-5-backend.{DOMAIN}",
        f"Not public: student-5-database.{DOMAIN}",
    }


def test_missing_headers_a_banner_no_redirect_and_a_public_backend_fail(monkeypatch):
    url = f"https://shared-ui.{DOMAIN}"
    fake_endpoints(
        monkeypatch,
        {
            url: (200, {"Server": "nginx/1.31.7", "X-Frame-Options": "DENY"}),
            f"http://shared-ui.{DOMAIN}": (200, {}),
            f"https://shared-backend.{DOMAIN}/health": (200, {}),
        },
    )
    failed = {
        name: detail for name, ok, detail in smoke_test.security_checks([url]) if not ok
    }
    assert failed == {
        f"Security headers on {url}": "missing Strict-Transport-Security, "
        "X-Content-Type-Options, Referrer-Policy, Permissions-Policy",
        f"Server software hidden on {url}": "nginx/1.31.7",
        f"HTTP redirects to HTTPS on shared-ui.{DOMAIN}": 200,
        f"Not public: shared-backend.{DOMAIN}": 200,
    }


def test_local_http_urls_skip_the_cloud_only_checks(monkeypatch):
    fake_endpoints(monkeypatch, {"http://localhost:8085": secure()})
    results = list(smoke_test.security_checks(["http://localhost:8085"]))
    assert [(name, ok) for name, ok, _ in results] == [
        ("Security headers on http://localhost:8085", True),
        ("Server software hidden on http://localhost:8085", True),
    ]


def app(name, external, env=(), registries=None):
    return {
        "name": name,
        "properties": {
            "configuration": {
                "ingress": {"external": external, "allowInsecure": False},
                "registries": [{"server": "r.io", "identity": PULL_IDENTITY}]
                if registries is None
                else registries,
            },
            "template": {"containers": [{"env": list(env)}]},
        },
    }


SECURE_APPS = [
    app("shared-ui", True),
    app(
        "student-5-frontend",
        True,
        [{"name": "UVICORN_SERVER_HEADER", "value": "false"}],
    ),
    # pragma: allowlist nextline secret - Azure secret reference name, not a value
    app("student-5-backend", False, [{"name": "DB_TOKEN", "secretRef": "db-token"}]),
    app("student-5-database", False),
]
SECURE_REGISTRY = {"adminUserEnabled": False, "anonymousPullEnabled": False}


def failures(apps, registry):
    return {n: d for n, ok, d in security_check.checks(apps, registry) if not ok}


def test_the_deployed_configuration_passes():
    assert failures(SECURE_APPS, SECURE_REGISTRY) == {}


def test_insecure_configuration_fails_each_control():
    apps = [
        app("shared-ui", True),
        app("student-5-backend", True),
        app(
            "student-5-database",
            False,
            [{"name": "STUDENT5_DATABASE_TOKEN", "value": ""}],
            registries=[
                {"server": "r.io", "username": "reg", "passwordSecretRef": "p"}
            ],
        ),
    ]
    apps[0]["properties"]["configuration"]["ingress"]["allowInsecure"] = True
    registry = {"adminUserEnabled": True, "anonymousPullEnabled": True}
    assert failures(apps, registry) == {
        "Only shared-ui and the frontends are public": "exposed: student-5-backend",
        "Public apps redirect HTTP to HTTPS": "shared-ui",
        "Images pulled with a managed identity": "student-5-database",
        "No credentials in plain app settings": (
            "student-5-database:STUDENT5_DATABASE_TOKEN"
        ),
        "Registry admin user disabled": True,
        "Registry anonymous pull disabled": True,
    }


def test_the_script_reads_az_json_and_exits_non_zero_on_failure(tmp_path, capsys):
    apps_file = tmp_path / "apps.json"
    registry_file = tmp_path / "registry.json"
    apps_file.write_text(json.dumps(SECURE_APPS))
    registry_file.write_text(json.dumps(SECURE_REGISTRY))
    assert security_check.main(apps_file, registry_file) == 0
    assert "| Registry admin user disabled | pass | False |" in capsys.readouterr().out
    registry_file.write_text(json.dumps({"adminUserEnabled": True}))
    assert security_check.main(apps_file, registry_file) == 1
