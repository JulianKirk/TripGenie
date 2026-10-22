"""Only the cloud profile lets the frontends trust forwarded proxy headers."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENV_FILES = ROOT / "shared" / "configuration"


def frontend_trust(*env_file: str) -> dict[str, str | None]:
    compose = ["docker", "compose", "-f", str(ROOT / "docker-compose.yml")]
    for name in env_file:
        compose += ["--env-file", str(ENV_FILES / name)]
    config = subprocess.run(  # noqa: S603 - fixed argv, no user input
        [*compose, "config", "--format", "json"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    services = json.loads(config)["services"]
    # Every service whose environment mentions the variable, so it cannot
    # spread to backends or databases unnoticed.
    trusted = {
        name: (service.get("environment") or {}).get("FORWARDED_ALLOW_IPS")
        for name, service in services.items()
        if "FORWARDED_ALLOW_IPS" in (service.get("environment") or {})
    }
    # shared-ui is nginx serving static files; it builds no URLs.
    assert set(trusted) == {f"student-{n}-frontend" for n in range(1, 6)}
    return trusted


def test_local_frontends_keep_uvicorns_loopback_only_default():
    assert set(frontend_trust().values()) == {"127.0.0.1"}
    assert set(frontend_trust(".env.example").values()) == {"127.0.0.1"}


def test_cloud_frontends_trust_the_https_ingress():
    assert set(frontend_trust(".env.cloud").values()) == {"*"}
