from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "graphify-update.yml"
AGENT_INSTRUCTIONS = ROOT / "AGENTS.md"


def test_graphify_workflow_has_safe_update_contract() -> None:
    document = yaml.load(WORKFLOW.read_text(), Loader=yaml.BaseLoader)

    triggers = document["on"]
    push = triggers["push"]
    assert push["branches"] == ["main"]
    assert push["paths-ignore"] == ["graphify-out/**"]
    assert "workflow_dispatch" in triggers

    assert document["permissions"] == {"contents": "write"}
    assert document["concurrency"]["cancel-in-progress"] == "false"

    job = document["jobs"]["update-graph"]
    steps = job["steps"]
    run_commands = "\n".join(step.get("run", "") for step in steps)

    assert "graphifyy==0.8.44" in run_commands
    assert "graphify update ." in run_commands
    assert "graphify-out/graph.json" in run_commands
    assert "graphify-out/graph.html" in run_commands
    assert "graphify-out/GRAPH_REPORT.md" in run_commands
    assert "git add --" in run_commands
    assert "git add -A" not in run_commands

    instructions = AGENT_INSTRUCTIONS.read_text()
    assert "graphify-out/GRAPH_REPORT.md" in instructions
    assert "graphify-out/graph.json" in instructions
    assert "contributors do not need local Git hooks" in instructions
    assert not (ROOT / "scripts" / "setup-graphify.sh").exists()


if __name__ == "__main__":
    test_graphify_workflow_has_safe_update_contract()
    print("graphify GitHub Actions workflow test: PASS")
