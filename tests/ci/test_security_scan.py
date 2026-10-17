"""Regression checks for the local Release 2 security gate (no live services)."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "security" / "scan.py"
SPEC = importlib.util.spec_from_file_location("security_scan", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
security = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(security)


@pytest.fixture
def snapshot(tmp_path):
    directory = tmp_path / "scripts" / "security"
    directory.mkdir(parents=True)
    (directory / "secret-allowlist.toml").write_text("allowlist = []\n")
    return tmp_path


def test_hook_always_scans_all_files_with_pinned_dependencies():
    config = yaml.safe_load((ROOT / ".pre-commit-config.yaml").read_text())
    hook = config["repos"][0]["hooks"][0]
    assert hook["id"] == "security"
    assert hook["language"] == "python"
    assert hook["entry"] == "python scripts/security/scan.py"
    assert hook["always_run"] is True
    assert hook["pass_filenames"] is False
    assert hook["stages"] == ["pre-commit", "manual"]
    requirements = (ROOT / "scripts" / "security" / "requirements.txt").read_text()
    assert all(
        pin in requirements.splitlines() for pin in hook["additional_dependencies"]
    )


def test_dependency_collection_includes_runtime_and_all_extras(tmp_path):
    for name, dependency in (
        ("student-1", "httpx>=0.27"),
        ("shared", "fastapi>=0.115"),
    ):
        directory = tmp_path / name
        directory.mkdir()
        (directory / "pyproject.toml").write_text(
            f'[project]\ndependencies = ["{dependency}"]\n'
            '[project.optional-dependencies]\ndev = ["pytest>=9.0.3"]\n'
        )
    assert security.collect_dependencies(tmp_path) == [
        "fastapi>=0.115",
        "httpx>=0.27",
        "pytest>=9.0.3",
    ]


@pytest.mark.parametrize("dynamic", ["dependencies", "optional-dependencies"])
def test_dynamic_dependency_definitions_fail_closed(tmp_path, dynamic):
    (tmp_path / "pyproject.toml").write_text(f'[project]\ndynamic = ["{dynamic}"]\n')
    with pytest.raises(ValueError, match="Dynamic dependencies"):
        security.collect_dependencies(tmp_path)


def test_empty_dependency_audit_is_not_success(tmp_path):
    with pytest.raises(ValueError, match="empty audit"):
        security.collect_dependencies(tmp_path)


@pytest.mark.parametrize(
    ("tool", "returncode", "data", "expected"),
    [
        ("ruff", 0, None, "passed"),
        ("ruff", 1, None, "failed"),
        ("ruff", 2, None, "failed"),
        ("detect-secrets", 0, {"results": {}}, "passed"),
        ("detect-secrets", 1, {"results": {}}, "failed"),
        ("pip-audit", 0, {"dependencies": [{"name": "httpx", "vulns": []}]}, "passed"),
        ("pip-audit", 0, {"dependencies": []}, "failed"),
        ("pip-audit", 1, {"dependencies": [{"vulns": [{"id": "test"}]}]}, "failed"),
        ("pip-audit", 0, {"dependencies": [{"skip_reason": "unsupported"}]}, "failed"),
    ],
)
def test_scanner_exit_codes_and_results_fail_closed(
    snapshot, monkeypatch, tool, returncode, data, expected
):
    monkeypatch.setattr(security, "version", lambda _tool: "test")
    monkeypatch.setattr(
        security,
        "run",
        lambda _args, _cwd: subprocess.CompletedProcess(
            [], returncode, json.dumps(data) if data is not None else "", "diagnostic"
        ),
    )
    result = security.scan_tool(tool, [], snapshot)
    assert result["status"] == expected
    assert result["returncode"] == returncode
    assert result["stderr"] == "diagnostic"


@pytest.mark.parametrize(
    "output", ["not JSON", "{}", "[]", '{"results": []}', '{"dependencies": {}}']
)
@pytest.mark.parametrize("tool", ["detect-secrets", "pip-audit"])
def test_malformed_scanner_output_is_an_error(snapshot, monkeypatch, output, tool):
    monkeypatch.setattr(security, "version", lambda _tool: "test")
    monkeypatch.setattr(
        security,
        "run",
        lambda _args, _cwd: subprocess.CompletedProcess([], 0, output, ""),
    )
    result = security.scan_tool(tool, [], snapshot)
    assert result["status"] == "error"
    assert result["error"]


@pytest.mark.parametrize(
    "error",
    [
        FileNotFoundError("scanner missing"),
        subprocess.TimeoutExpired("scanner", 600),
        security.PackageNotFoundError("scanner"),
    ],
)
def test_scanner_unavailable_or_timeout_is_an_error(snapshot, monkeypatch, error):
    def unavailable(_args, _cwd):
        raise error

    monkeypatch.setattr(security, "version", lambda _tool: "test")
    monkeypatch.setattr(security, "run", unavailable)
    result = security.scan_tool("pip-audit", [], snapshot)
    assert result["status"] == "error"
    assert result["error"]


def test_allowlist_matches_only_reviewed_file_detector_and_hash(snapshot):
    allowlist = snapshot / "scripts" / "security" / "secret-allowlist.toml"
    allowlist.write_text(
        '[[allowlist]]\nfilename = "graphify-out/graph.json"\n'
        # pragma: allowlist nextline secret - synthetic fingerprint
        'type = "Hex High Entropy String"\nhashed_secret = "reviewed-fingerprint"\n'
        'reason = "Generated commit ID."\n'
    )
    finding = {
        "type": "Hex High Entropy String",
        "hashed_secret": "reviewed-fingerprint",  # pragma: allowlist secret - test hash
    }
    data = {"results": {"graphify-out\\graph.json": [finding]}}
    assert security.new_secrets(data, snapshot) == []
    for filename, changed in [
        ("other.json", finding),
        (
            "graphify-out/graph.json",
            # pragma: allowlist nextline secret - synthetic fingerprint
            {**finding, "hashed_secret": "new-value"},
        ),
        ("graphify-out/graph.json", {**finding, "type": "Secret Keyword"}),
    ]:
        assert security.new_secrets({"results": {filename: [changed]}}, snapshot) == [
            changed
        ]


def test_detect_secrets_zero_exit_with_findings_still_blocks(snapshot, monkeypatch):
    # pragma: allowlist nextline secret - synthetic fingerprint
    finding = {"type": "Secret Keyword", "hashed_secret": "new-value"}
    monkeypatch.setattr(security, "version", lambda _tool: "test")
    monkeypatch.setattr(
        security,
        "run",
        lambda _args, _cwd: subprocess.CompletedProcess(
            [], 0, json.dumps({"results": {"config.py": [finding]}}), ""
        ),
    )
    result = security.scan_tool("detect-secrets", [], snapshot)
    assert result["status"] == "failed"
    assert result["new_findings"] == [finding]


def test_real_ruff_blocks_unsafe_python_and_production_asserts(tmp_path):
    (tmp_path / "unsafe.py").write_text("eval(input())\nassert True\n")
    (tmp_path / ".gitignore").write_text("unsafe.py\n")
    (tmp_path / "pyproject.toml").write_text("[tool.ruff.lint]\nselect = []\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_sample.py").write_text("assert True\n")
    (tmp_path / "tests" / "test_unsafe.py").write_text("eval(input())\n")
    result = security.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--no-respect-gitignore",
            "--config",
            str(ROOT / "scripts" / "security" / "ruff.toml"),
            ".",
        ],
        tmp_path,
    )
    assert result.returncode == 1
    assert "S307" in result.stdout
    assert "S101" in result.stdout
    assert "test_sample.py:" not in result.stdout
    assert "test_unsafe.py:" in result.stdout


def test_real_detect_secrets_blocks_synthetic_token_without_disclosing_it(snapshot):
    synthetic = "ghp_" + hashlib.sha256(b"regression-fixture").hexdigest()[:36]
    (snapshot / "config.txt").write_text(f'access_token = "{synthetic}"\n')
    result = security.scan_tool(
        "detect-secrets",
        ["detect_secrets", "scan", "--all-files", "--no-verify", "."],
        snapshot,
    )
    assert result["status"] == "failed"
    assert result["returncode"] == 0
    assert result["new_findings"]
    assert synthetic not in json.dumps(result)


def test_security_test_fixtures_are_explicitly_allowlisted(snapshot):
    (snapshot / "test_security_scan.py").write_bytes(Path(__file__).read_bytes())
    result = security.scan_tool(
        "detect-secrets",
        ["detect_secrets", "scan", "--all-files", "--no-verify", "."],
        snapshot,
    )
    assert result["status"] == "passed", result


def test_scan_runs_every_tool_and_records_complete_scope(tmp_path, monkeypatch):
    (tmp_path / "app.py").write_text("print('hello')\n")
    (tmp_path / "deleted.py").touch()
    (tmp_path / "deleted.py").unlink()
    (tmp_path / "pyproject.toml").write_text(
        '[project]\ndependencies = ["httpx>=0.27"]\n'
    )
    (tmp_path / "requirements.txt").write_text("requests\n")
    seen = []

    def fake_git(_root, *args):
        return (
            "app.py\0deleted.py\0pyproject.toml\0requirements.txt\0"
            if args[0] == "ls-files"
            else "HEAD"
        )

    def scanner(name, command, snapshot):
        assert (snapshot / "app.py").is_file()
        assert not (snapshot / "deleted.py").exists()
        if name == "pip-audit":
            assert (snapshot / ".security-project-requirements.txt").read_text() == (
                "httpx>=0.27\n"
            )
            assert command.count("-r") == 2
            assert "requirements.txt" in command
        seen.append(name)
        return {"tool": name, "status": "failed" if name == "ruff" else "passed"}

    monkeypatch.setattr(security, "git", fake_git)
    monkeypatch.setattr(security, "scan_tool", scanner)
    report = security.scan(tmp_path)
    assert seen == ["ruff", "detect-secrets", "pip-audit"]
    assert report["status"] == "failed"
    assert report["dependency_manifests"] == ["pyproject.toml", "requirements.txt"]
    assert report["files"] == ["app.py", "pyproject.toml", "requirements.txt"]
    assert len(report["content_sha256"]) == 64
    assert report["started_at"] <= report["finished_at"]


def test_git_scope_includes_staged_and_new_files_but_not_ignored_files(
    tmp_path, monkeypatch
):
    assert security.GIT is not None
    assert security.run([security.GIT, "init", "--quiet"], tmp_path).returncode == 0
    (tmp_path / ".gitignore").write_text("*.env\n")
    (tmp_path / "tracked.env").write_text("example=true\n")
    (tmp_path / "local.env").write_text("example=true\n")
    (tmp_path / "new.py").write_text("print('new')\n")
    assert (
        security.run(
            [security.GIT, "add", "--force", "tracked.env"], tmp_path
        ).returncode
        == 0
    )
    real_git = security.git

    def git(root, *args):
        return real_git(root, *args) if args[0] == "ls-files" else "unborn"

    (tmp_path / "pyproject.toml").write_text('[project]\ndependencies = ["httpx"]\n')
    monkeypatch.setattr(security, "git", git)
    monkeypatch.setattr(
        security,
        "scan_tool",
        lambda name, _args, _cwd: {"tool": name, "status": "passed"},
    )
    report = security.scan(tmp_path)
    assert report["status"] == "passed"
    assert "tracked.env" in report["files"]
    assert "new.py" in report["files"]
    assert "local.env" not in report["files"]
    assert not any(".git" in Path(name).parts for name in report["files"])


@pytest.mark.parametrize(
    ("status", "exit_code"), [("passed", 0), ("failed", 1), ("error", 1)]
)
def test_cli_replaces_stale_report_and_returns_blocking_exit_code(
    tmp_path, monkeypatch, status, exit_code
):
    report = tmp_path / "report.json"
    report.write_text('{"status": "passed", "stale": true}')
    monkeypatch.setattr(sys, "argv", ["scan.py", "--report", str(report)])
    monkeypatch.setattr(security, "git", lambda _root, *_args: str(tmp_path))
    monkeypatch.setattr(
        security, "scan", lambda _root: {"status": status, "checks": []}
    )
    assert security.main() == exit_code
    assert json.loads(report.read_text()) == {"status": status, "checks": []}
