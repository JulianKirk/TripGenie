# Student 1 pre-commit security testing report (Release 2)

Issue: #175. Scope: Student 1's contribution, namely `student-1/**`,
`ai-services/rag-server/**`, the Azure deployment scripts
`scripts/deploy/azure/**` and `tests/ci/test_compose_to_azure.py`.

The shared gate was added in #165. This report covers running it on Student 1's
contribution, triaging what it found, and showing it block a commit.

## Tools and versions

| Tool | Version | What it checks |
| --- | --- | --- |
| pre-commit | 4.5.1 | Runs the `security` hook at the `pre-commit` stage |
| Ruff | 0.16.5 | Every stable `S` (flake8-bandit) rule, using `scripts/security/ruff.toml` |
| detect-secrets | 1.5.0 | All detectors on every tracked or non-ignored file, with verification turned off (`--no-verify`) |
| pip-audit | 2.10.0 | Runtime and optional dependencies from every `pyproject.toml` and `requirements*.txt` file, including transitive dependencies |

Environment: Python 3.12.4 (pre-commit's isolated hook environment) on macOS
(darwin). Scanned HEAD was `0736601` (origin/main when the branch was cut).

## Hook configuration and trigger

`.pre-commit-config.yaml` defines a single local hook:

```yaml
- id: security
  entry: python scripts/security/scan.py
  language: python
  additional_dependencies: [ruff==0.16.5, detect-secrets==1.5.0, pip-audit==2.10.0]
  pass_filenames: false
  always_run: true
  stages: [pre-commit, manual]
```

`pre-commit install` writes `.git/hooks/pre-commit`. From then on, every
`git commit` runs `scan.py` before the commit is created. The script works on a
temporary copy of all Git-eligible files. pre-commit stashes unstaged edits, so
the copy holds what is being committed. The script runs all three tools and
exits non-zero if any of them fails or errors, and a non-zero exit aborts the
commit. The full JSON evidence is written to
`$(git rev-parse --git-path security-reports/latest.json)`.

`scan.py` has no path filter: it always scans the whole repository. To isolate
Student 1's files I also ran Ruff and detect-secrets directly on Student 1's
paths, using the same configuration.

## Commands run

```bash
python3.12 -m venv venv-precommit
venv-precommit/bin/pip install -r scripts/security/requirements.txt
pre-commit install
pre-commit run security --all-files --verbose

# Scoped to Student 1 (same config as the hook)
ruff check --no-cache --no-respect-gitignore --config scripts/security/ruff.toml \
  --output-format concise student-1 ai-services/rag-server scripts/deploy/azure \
  tests/ci/test_compose_to_azure.py
ruff check ... --ignore-noqa ...   # same paths: shows what the existing suppressions hide
detect-secrets scan --all-files --no-verify student-1 ai-services/rag-server \
  scripts/deploy/azure tests/ci/test_compose_to_azure.py
```

## Results

### Full-repository hook run

```text
$ pre-commit run security --all-files --verbose
Ruff security, detect-secrets and pip-audit..............................Passed
- hook id: security
- duration: 28.51s

ruff: passed
detect-secrets: passed
pip-audit: passed
Security gate: passed. Report: <repo>/.git/worktrees/<worktree>/security-reports/latest.json
```

Details from the JSON report:

- 676 files scanned and 28 dependency manifests audited.
- Ruff printed `All checks passed!` with exit code 0.
- detect-secrets reported raw results only in `graphify-out/graph.html` and
  `graphify-out/graph.json`. Both match the two entries in
  `scripts/security/secret-allowlist.toml`, so there were 0 new findings.
- pip-audit resolved and audited 88 packages and found 0 vulnerabilities and 0
  skipped packages.

### Scoped to Student 1 paths

- **Ruff:** `All checks passed!` (exit 0) across 130 tracked files.
- **detect-secrets:** `"results": {}`, so no potential secrets were found.
- **Ruff with `--ignore-noqa`:** 16 findings. Every one already has a reviewed
  inline suppression from #165. I re-checked each one; they are listed below.

### pip-audit on Student 1 dependencies

Student 1 and the RAG server declare version ranges, not exact pins. pip-audit
audits the versions that resolve at scan time:

| Requirement (`student-1/**/pyproject.toml`, `ai-services/rag-server/pyproject.toml`) | Resolved and audited | Vulnerabilities |
| --- | --- | --- |
| `fastapi>=0.115,<1.0` | 0.156.2 | 0 |
| `httpx>=0.27,<1.0` | 0.28.1 | 0 |
| `jinja2>=3.1,<4.0` | 3.1.6 | 0 |
| `pydantic>=2.8,<3.0` | 2.14.1 | 0 |
| `python-multipart>=0.0.9,<1.0` | 0.0.32 | 0 |
| `uvicorn[standard]>=0.30,<1.0` | 0.54.0 | 0 |
| `pytest>=9.0.3,<10.0` (dev) | 9.1.1 | 0 |
| `ruff>=0.6,<1.0` (dev) | 0.16.5 | 0 |

There were no vulnerable versions, so no dependency changed. The result only
covers these resolved versions: an environment that installs an older version
inside a range is not covered by this scan (the README states the same limit).

## Findings

| Tool | File:line | Finding | Severity | Resolution |
| --- | --- | --- | --- | --- |
| Ruff | `student-1/database/database_service/repository.py:340` | S608 SQL built from strings | Medium (Bandit B608) | Suppressed (existing `# noqa: S608 - constant columns`). The f-string only joins the module constant `TRIP_FIELDS`. Filters are added as `?` placeholders with bound `params`. |
| Ruff | `student-1/database/database_service/repository.py:422, 521, 566, 597, 612, 652, 682, 697, 743, 773, 812, 826` (12 sites) | S608 SQL built from strings | Medium (Bandit B608) | Suppressed (existing `# noqa: S608 - constant columns; bound values`). Column lists come from module-level tuple constants (`ITEM_FIELDS`, `TRIP_*_FIELDS`), and every value is a bound `?` parameter. |
| Ruff | `ai-services/rag-server/tests/test_service.py:203-204` | S105 possible hard-coded password (`query_secret`, `source_secret`) | Low | Suppressed (existing `# noqa: S105` plus `# pragma: allowlist secret`). These are synthetic strings used to check that logs are redacted, not credentials. |
| Ruff | `tests/ci/test_compose_to_azure.py:109` | S603 `subprocess` call | Low | Suppressed (existing `# noqa: S603 - fixed argv, no user input`). The argument list is the literal `docker compose -f <repo>/docker-compose.yml config --format json`, with no shell. |
| detect-secrets | (none) | No findings in Student 1 paths | - | - |
| pip-audit | (none) | 0 vulnerabilities in the resolved Student 1 and RAG dependencies | - | - |

Totals for Student 1's paths:

- Ruff: 16 findings, all false positives that were already suppressed with a
  reason. I re-reviewed them and kept them; 0 are open.
- detect-secrets: 0 findings.
- pip-audit: 0 findings.
- No code changes were needed.

Out of scope (other students' code): the full-repository run reported no open
findings anywhere. The only raw detect-secrets results are the two Graphify
checksums already in the allowlist.

## Blocked commit, then fix, then passing commit

This was done on a throwaway branch (`scratch/precommit-demo`), which was
deleted afterwards, so none of it is in this PR. I appended deliberately unsafe
code to `student-1/backend/backend_service/config.py`:

```python
# Deliberately unsafe demo code for the blocked-commit evidence.
import subprocess  # noqa: E402

DEMO_AWS_ACCESS_KEY_ID = "AKIA<redacted: synthetic 20-character key>"


def run_demo(cmd: str) -> int:
    return subprocess.call(cmd, shell=True)
```

### 1. Commit blocked (exit 1, no commit created)

```text
$ git add student-1/backend/backend_service/config.py
$ git commit -m "demo: unsafe change (expected to be blocked)"
Ruff security, detect-secrets and pip-audit..............................Failed
- hook id: security
- exit code: 1

ruff: failed
student-1/backend/backend_service/config.py:356:12: S602 `subprocess` call with `shell=True` identified, security issue
Found 1 error.

detect-secrets: failed
[
  {
    "type": "AWS Access Key",
    "filename": "student-1/backend/backend_service/config.py",
    "hashed_secret": "<redacted>",
    "is_verified": false,
    "line_number": 352
  }
]
pip-audit: passed
Security gate: failed. Report: <repo>/.git/worktrees/<worktree>/security-reports/latest.json

$ git log --oneline -1
0736601 Release 2: Azure Container Apps deployment following Lab 11 (scripts + cloud-deployment.yml) (#179)
```

### 2. Fix

I removed the hard-coded key and the shell call. The value is now read from
the environment, and no subprocess is started:

```python
# Demo fix: credentials come from the environment and no shell is spawned.
DEMO_AWS_ACCESS_KEY_ID = os.environ.get("DEMO_AWS_ACCESS_KEY_ID", "")
```

### 3. Commit passes (exit 0)

```text
$ git add student-1/backend/backend_service/config.py
$ git commit -m "demo: fixed change (expected to pass)"
Ruff security, detect-secrets and pip-audit..............................Passed
[scratch/precommit-demo a915026] demo: fixed change (expected to pass)
 1 file changed, 4 insertions(+)
```

The commit that adds this report also ran through the installed hook (see the
PR description).

Sanitising: local absolute paths are replaced with `<repo>`/`<worktree>`. The
synthetic key and its SHA-1 fingerprint are redacted so that this report does
not trip detect-secrets itself. Nothing else was changed.

## Regression checks

The packages were installed as in `.github/workflows/student-1-ci.yml`:
`pip install -e ai-services/ai-mode`, `-e ./student-1[dev]` and
`-e ./ai-services/rag-server[dev]`.

| Suite | Result |
| --- | --- |
| `student-1/tests` (database, backend, frontend) | 288 passed |
| `ai-services/rag-server` | 42 passed |
| `pytest tests/ci .github/tests` (with `scripts/security/requirements.txt` installed, as in `workflow-policy-ci.yml`) | 50 passed |

## Summary

- The pre-commit security gate is installed locally and runs on every
  `git commit`.
- It passes on the full repository and on Student 1's contribution.
- The 16 Ruff `S` findings in Student 1's paths are all reviewed false
  positives with inline justifications (13 S608 on constant column lists with
  bound parameters, 2 S105 test fixtures, 1 S603 fixed argv). They were kept
  as they are.
- detect-secrets and pip-audit reported nothing for Student 1, so no
  dependency bump was needed.
- The hook was shown blocking a commit with a hard-coded AWS-style key and
  `shell=True`, then accepting the fixed commit.
