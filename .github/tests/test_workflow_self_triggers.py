from pathlib import Path

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = REPOSITORY_ROOT / ".github" / "workflows"
POLICY_WORKFLOW = "workflow-policy-ci.yml"
EXEMPT_WORKFLOWS = {
    "cloud-deployment.yml",
    "graphify-update.yml",
}


def test_non_exempt_workflows_trigger_when_their_definition_changes():
    workflow_files = sorted((*WORKFLOWS.glob("*.yml"), *WORKFLOWS.glob("*.yaml")))
    assert POLICY_WORKFLOW in {path.name for path in workflow_files}

    violations = []
    for workflow_file in workflow_files:
        if workflow_file.name in EXEMPT_WORKFLOWS:
            continue

        workflow = yaml.load(workflow_file.read_text(), Loader=yaml.BaseLoader)
        events = workflow.get("on", {})
        own_path = f".github/workflows/{workflow_file.name}"

        for event_name in ("push", "pull_request"):
            event = events.get(event_name, {})
            paths = event.get("paths", []) if isinstance(event, dict) else []
            if own_path not in paths:
                violations.append(
                    f"{workflow_file.name}: {event_name}.paths misses {own_path}"
                )

    assert not violations, "\n" + "\n".join(violations)
