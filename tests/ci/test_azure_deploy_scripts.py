"""Run the Azure deploy scripts against stub az, gh, git and docker commands.

Nothing here reaches Azure or GitHub: each stub prints canned answers and
records its arguments, so these show what the scripts would do, not that a
real deployment works.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts" / "deploy" / "azure"
CANONICAL = "YourNightmareIsOver/TripGenie"
SUBJECT = "repo:YourNightmareIsOver@345580038/TripGenie@1341299908"
PULL_IDENTITY = (
    "/subscriptions/s/resourceGroups/rg-tripgenie/providers/"
    "Microsoft.ManagedIdentity/userAssignedIdentities/tripgenie-acr-pull"
)
QUICKSTART = "mcr.microsoft.com/k8se/quickstart:latest"


def find_bash():
    if os.name == "nt":
        # Not System32's bash.exe, which is WSL, nor Git's bin\bash.exe, which
        # puts its own tools ahead of the stubs on PATH.
        git_bash = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
        git_bash = git_bash / "Git" / "usr" / "bin" / "bash.exe"
        return str(git_bash) if git_bash.exists() else None
    return shutil.which("bash")


BASH = find_bash()
pytestmark = pytest.mark.skipif(BASH is None, reason="needs bash")

# Each stub logs "<command> <args>" to $STUB_CALLS, then answers by arguments.
STUBS = {
    "git": 'echo "https://github.com/JulianKirk/TripGenie.git"',
    "gh": r"""
case "$*" in
  "auth status") ;;
  "api repos/JulianKirk/TripGenie --jq .full_name")
    echo "YourNightmareIsOver/TripGenie" ;;
  "api repos/YourNightmareIsOver/TripGenie/actions/oidc/customization/sub"*)
    [ -n "$STUB_OIDC_FAIL" ] && { echo "HTTP 404" >&2; exit 1; }
    printf '%s\n' "$STUB_OIDC" ;;
  "secret set"*) ;;
  *) echo "unexpected gh $*" >&2; exit 99 ;;
esac
""",
    "docker": 'cat "$STUB_COMPOSE"',
    "sleep": ":",
    "az": r"""
arg() {
  local previous=""
  for a in "$@"; do [ "$previous" = "$FLAG" ] && echo "$a"; previous=$a; done
}
NAME=$(FLAG=--name arg "$@")
case "$*" in
  "account show --query id"*) echo sub-id ;;
  "account show --query tenantId"*) echo tenant-id ;;
  "account show"*) ;;
  "group exists"*) echo true ;;
  "group show"*tags.registryName*) echo reg ;;
  "group show"*tags.envName*) echo env ;;
  "group show"*) echo /subscriptions/sub-id/resourceGroups/rg-tripgenie ;;
  "identity create"*) echo client-id ;;
  "identity show"*principalId*) echo principal-id ;;
  "identity show"*) echo "$PULL_IDENTITY" ;;
  "role assignment list"*) echo existing ;;
  "acr show"*) echo r.io ;;
  "containerapp env show"*) echo env.example.io ;;
  "containerapp show"*)
    COUNT=$(cat "$STUB_CALLS.$NAME" 2>/dev/null || echo 0)
    echo $((COUNT + 1)) > "$STUB_CALLS.$NAME"
    if [ "$STUB_REVISION" = activating ] && [ "$COUNT" -lt 2 ]; then
      echo "$NAME--2|$NAME--1"
    elif [ "$STUB_REVISION" = ready ] || [ "$STUB_REVISION" = activating ]; then
      echo "$NAME--2|$NAME--2"
    else
      echo "$NAME--2|$NAME--1"
    fi ;;
  "containerapp revision show"*)
    WANT="r.io/tripgenie-$NAME:$IMAGE_TAG"
    case "$STUB_REVISION" in
      ready) echo "Healthy|Running|$WANT" ;;
      activating) echo "None|Activating|$WANT" ;;
      placeholder) echo "Unhealthy|ActivationFailed|$QUICKSTART" ;;
      failed) echo "Unhealthy|ActivationFailed|$WANT" ;;
    esac ;;
  "containerapp list"*) ;;
  "provider register"* | "group create"* | "identity federated-credential create"* \
    | "containerapp create"*) ;;
  *) echo "unexpected az $*" >&2; exit 99 ;;
esac
""",
}

COMPOSE = {
    "services": {
        "student-1-frontend": {
            "build": {},
            "ports": [{"target": 8081, "published": "8081"}],
        },
        "student-1-database": {"build": {}, "expose": ["8002"]},
    }
}


def run(
    script: str, tmp_path: Path, **env: str
) -> tuple[subprocess.CompletedProcess, list[str]]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "calls"
    stubs = {**STUBS, "python3": f'exec "{Path(sys.executable).as_posix()}" "$@"'}
    for name, body in stubs.items():
        stub = bin_dir / name
        log = 'echo "$(basename "$0") $*" >> "$STUB_CALLS"\n'
        stub.write_text(f"#!/bin/bash\n{log}{body}\n", newline="\n")
        stub.chmod(0o755)
    compose = tmp_path / "compose.json"
    compose.write_text(json.dumps(COMPOSE))
    result = subprocess.run(  # noqa: S603 - fixed argv, stub commands only
        [BASH, (SCRIPTS / script).as_posix()],
        capture_output=True,
        text=True,
        timeout=120,
        env={
            **os.environ,
            # Stubs first, then bash's own tools (sed, seq, ...).
            "PATH": os.pathsep.join(
                [str(bin_dir), str(Path(BASH).parent), os.environ["PATH"]]
            ),
            "STUB_CALLS": calls.as_posix(),
            "STUB_COMPOSE": compose.as_posix(),
            "PULL_IDENTITY": PULL_IDENTITY,
            "QUICKSTART": QUICKSTART,
            "IMAGE_TAG": "abc",
            **env,
        },
    )
    lines = calls.read_text().splitlines() if calls.exists() else []
    return result, lines


def test_secrets_setup_trusts_githubs_subject_even_from_a_stale_remote(tmp_path):
    result, calls = run("gh-secrets-setup.sh", tmp_path, STUB_OIDC=f"true\t{SUBJECT}")
    assert result.returncode == 0, result.stderr
    assert "git config --get remote.origin.url" in calls
    federated = [c for c in calls if "federated-credential create" in c]
    assert len(federated) == 1
    assert f"--subject {SUBJECT}:environment:production " in federated[0]
    secrets = [c for c in calls if c.startswith("gh secret set")]
    assert len(secrets) == 3
    assert all(f"--repo {CANONICAL} " in c for c in secrets)


@pytest.mark.parametrize(
    "oidc",
    [
        {"STUB_OIDC_FAIL": "1"},
        {"STUB_OIDC": "false\t"},
        {"STUB_OIDC": "true\t"},
    ],
    ids=["api-error", "custom-template", "no-prefix"],
)
def test_secrets_setup_stops_before_azure_without_githubs_subject(tmp_path, oidc):
    result, calls = run("gh-secrets-setup.sh", tmp_path, **oidc)
    assert result.returncode != 0
    assert not [c for c in calls if c.startswith("gh secret")]
    # Only Azure reads ran: nothing was registered, created or federated.
    assert [c for c in calls if c.startswith("az")] == ["az account show"]


def test_deploy_pulls_with_the_identity_and_waits_for_the_new_revision(tmp_path):
    result, calls = run("deploy-azure.sh", tmp_path, STUB_REVISION="activating")
    assert result.returncode == 0, result.stderr
    assert "=== Deployment Complete ===" in result.stdout
    assert (
        "student-1-database: revision student-1-database--2 is ready" in result.stdout
    )
    creates = [c for c in calls if "containerapp create" in c]
    assert len(creates) == 2
    assert all(f"--registry-identity {PULL_IDENTITY} " in c for c in creates)
    assert "sleep 10" in calls


@pytest.mark.parametrize(
    ("revision", "reason"),
    [
        (
            "placeholder",
            f"runs {QUICKSTART}, not r.io/tripgenie-student-1-database:abc",
        ),
        ("failed", "is ActivationFailed; student-1-database--1 still serves traffic"),
    ],
)
def test_deploy_fails_when_the_new_revision_is_not_serving(tmp_path, revision, reason):
    result, _ = run("deploy-azure.sh", tmp_path, STUB_REVISION=revision)
    assert result.returncode != 0
    assert (
        f"student-1-database: newest revision student-1-database--2 {reason}"
        in result.stderr
    )
    assert "Deployment Complete" not in result.stdout
