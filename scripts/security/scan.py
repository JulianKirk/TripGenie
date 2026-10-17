"""Run the Release 2 commit gate and retain redacted, machine-readable evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import tomllib

TIMEOUT_SECONDS = 600
GIT = shutil.which("git")


def run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed tools, argument arrays, no shell
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=TIMEOUT_SECONDS,
        check=False,
    )


def git(root: Path, *args: str) -> str:
    if GIT is None:
        message = "Git is required for the security gate."
        raise FileNotFoundError(message)
    result = run([GIT, *args], root)
    if result.returncode:
        raise RuntimeError(result.stderr)
    return result.stdout.strip()


def collect_dependencies(snapshot: Path) -> list[str]:
    dependencies: set[str] = set()
    for path in snapshot.rglob("pyproject.toml"):
        project = tomllib.loads(path.read_text(encoding="utf-8")).get("project", {})
        if {"dependencies", "optional-dependencies"} & set(project.get("dynamic", [])):
            message = f"Dynamic dependencies require audit support: {path}"
            raise ValueError(message)
        dependencies.update(project.get("dependencies", []))
        for group in project.get("optional-dependencies", {}).values():
            dependencies.update(group)
    if not dependencies:
        message = "No project dependencies found; refusing an empty audit."
        raise ValueError(message)
    return sorted(dependencies)


def new_secrets(data: dict, snapshot: Path) -> list[dict]:
    allowlist = tomllib.loads(
        (snapshot / "scripts" / "security" / "secret-allowlist.toml").read_text(
            encoding="utf-8"
        )
    )["allowlist"]
    allowed = {
        (item["filename"], item["type"], item["hashed_secret"])
        for item in allowlist
        if item["reason"].strip()
    }
    return [
        finding
        for filename, findings in data["results"].items()
        for finding in findings
        if (filename.replace("\\", "/"), finding["type"], finding["hashed_secret"])
        not in allowed
    ]


def scan_tool(name: str, args: list[str], snapshot: Path) -> dict:
    started = time.monotonic()
    result: dict = {"tool": name, "command": args, "status": "error"}
    try:
        result["version"] = version(name)
        process = run([sys.executable, "-m", *args], snapshot)
        result.update(
            returncode=process.returncode,
            stderr=process.stderr,
            stdout=process.stdout,
        )
        if name == "detect-secrets":
            data = json.loads(process.stdout)
            if not isinstance(data, dict) or not isinstance(data.get("results"), dict):
                message = "detect-secrets returned an invalid results object."
                raise ValueError(message)
            result["data"] = data
            result["new_findings"] = new_secrets(data, snapshot)
            passed = process.returncode == 0 and not result["new_findings"]
        elif name == "pip-audit":
            data = json.loads(process.stdout)
            if not isinstance(data, dict) or not isinstance(
                data.get("dependencies"), list
            ):
                message = "pip-audit returned an invalid dependencies list."
                raise ValueError(message)
            result["data"] = data
            passed = (
                process.returncode == 0
                and bool(data["dependencies"])
                and all(
                    isinstance(item, dict)
                    and "skip_reason" not in item
                    and item.get("vulns") == []
                    for item in data["dependencies"]
                )
            )
        else:
            passed = process.returncode == 0
        result["status"] = "passed" if passed else "failed"
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        PackageNotFoundError,
        subprocess.TimeoutExpired,
    ) as exc:
        result["error"] = str(exc)
    result["duration_seconds"] = round(time.monotonic() - started, 3)
    return result


def scan(root: Path) -> dict:
    files = sorted(
        set(
            git(
                root, "ls-files", "-z", "--cached", "--others", "--exclude-standard"
            ).split("\0")
        )
        - {""}
    )
    report: dict = {
        "schema_version": 1,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "head": git(root, "rev-parse", "HEAD"),
        "python": sys.version,
        "platform": sys.platform,
        "scope": (
            "All tracked and non-ignored new files; "
            "pre-commit stashes unstaged edits in commit mode."
        ),
        "status": "error",
        "checks": [],
    }
    digest = hashlib.sha256()
    with tempfile.TemporaryDirectory(prefix="tripgenie-security-") as directory:
        snapshot = Path(directory)
        scanned = []
        for name in files:
            source = root / name
            if not source.is_file():
                continue
            if source.is_symlink():
                message = f"Refusing to scan a symlink outside its Git object: {name}"
                raise ValueError(message)
            destination = snapshot / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            digest.update(
                name.encode("utf-8") + b"\0" + destination.read_bytes() + b"\0"
            )
            scanned.append(name)
        report["files"] = scanned
        report["content_sha256"] = digest.hexdigest()
        manifests = sorted(
            name
            for name in scanned
            if Path(name).name == "pyproject.toml"
            or (Path(name).name.startswith("requirements") and name.endswith(".txt"))
        )
        report["dependency_manifests"] = manifests
        commands = [
            (
                "ruff",
                [
                    "ruff",
                    "check",
                    "--no-cache",
                    "--no-respect-gitignore",
                    "--config",
                    "scripts/security/ruff.toml",
                    "--output-format",
                    "concise",
                    ".",
                ],
            ),
            (
                "detect-secrets",
                ["detect_secrets", "scan", "--all-files", "--no-verify", "."],
            ),
        ]
        for name, command in commands:
            report["checks"].append(scan_tool(name, command, snapshot))
        try:
            requirements = snapshot / ".security-project-requirements.txt"
            requirements.write_text(
                "\n".join(collect_dependencies(snapshot)) + "\n", encoding="utf-8"
            )
            audit = [
                "pip_audit",
                "-r",
                requirements.name,
                "--format",
                "json",
                "--progress-spinner",
                "off",
            ]
            for name in manifests:
                if Path(name).name != "pyproject.toml":
                    audit.extend(["-r", name])
            report["checks"].append(scan_tool("pip-audit", audit, snapshot))
        except (OSError, ValueError) as exc:
            report["checks"].append(
                {"tool": "pip-audit", "status": "error", "error": str(exc)}
            )
    report["status"] = (
        "passed"
        if all(check["status"] == "passed" for check in report["checks"])
        else "failed"
    )
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, help="JSON evidence output path")
    args = parser.parse_args()
    root = Path(git(Path.cwd(), "rev-parse", "--show-toplevel"))
    output = args.report or root / git(
        root, "rev-parse", "--git-path", "security-reports/latest.json"
    )
    try:
        report = scan(root)
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        report = {"status": "error", "error": str(exc)}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for check in report.get("checks", []):
        print(f"{check['tool']}: {check['status']}")
        if check["status"] != "passed":
            detail = check.get("error") or check.get("stderr")
            if not detail and check["tool"] == "detect-secrets":
                detail = json.dumps(check.get("new_findings", []), indent=2)
            print((detail or check.get("stdout", ""))[:2000])
    print(f"Security gate: {report['status']}. Report: {output}")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
