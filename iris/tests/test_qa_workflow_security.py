import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "iris_qa_weekly.yml"


def test_weekly_workflow_has_no_untrusted_pr_or_stored_key_path():
    text = WORKFLOW.read_text(encoding="utf-8")
    workflow = yaml.load(text, Loader=yaml.BaseLoader)

    assert set(workflow["on"]) == {"schedule", "workflow_dispatch"}
    assert "pull_request" not in text
    assert "pull_request_target" not in text
    assert "secrets." not in text
    assert "IRIS_QA_AZURE_API_KEY" not in text
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["concurrency"] == {
        "group": "iris-qa-weekly",
        "cancel-in-progress": "false",
    }
    job = workflow["jobs"]["quality-assurance"]
    assert job["environment"] == "iris-qa-weekly"
    assert job["permissions"] == {"contents": "read", "id-token": "write"}
    assert job["env"]["AZURE_TOKEN_CREDENTIALS"] == "AzureCliCredential"
    assert job["if"] == (
        "github.repository == 'ls1intum/edutelligence' "
        "&& github.ref == 'refs/heads/main'"
    )

    steps = job["steps"]
    login = next(
        step
        for step in steps
        if step.get("name") == "Obtain short-lived Azure token through OIDC"
    )
    assert login["with"]["audience"] == "api://AzureADTokenExchange"

    run_bodies = "\n".join(step.get("run", "") for step in steps)
    assert "ACTIONS_ID_TOKEN_REQUEST_URL" not in run_bodies
    assert "ACTIONS_ID_TOKEN_REQUEST_TOKEN" not in run_bodies
    assert "az account get-access-token" not in run_bodies
    assert "printenv" not in run_bodies
    assert "set -x" not in run_bodies


def test_weekly_workflow_pins_actions_and_does_not_persist_git_credentials():
    workflow = yaml.load(WORKFLOW.read_text(), Loader=yaml.BaseLoader)
    steps = workflow["jobs"]["quality-assurance"]["steps"]
    external = [step["uses"] for step in steps if "uses" in step]

    assert external
    assert all(re.fullmatch(r"[^@]+@[0-9a-f]{40}", action) for action in external)
    checkout = next(
        step for step in steps if step.get("name") == "Checkout protected main commit"
    )
    assert checkout["with"]["ref"] == "${{ github.sha }}"
    assert checkout["with"]["persist-credentials"] == "false"


def test_weekly_workflow_calibrates_judge_before_candidate_spend():
    workflow = yaml.load(WORKFLOW.read_text(), Loader=yaml.BaseLoader)
    names = [
        step.get("name") for step in workflow["jobs"]["quality-assurance"]["steps"]
    ]

    assert names.index(
        "Run offline Iris and QA tests before Azure login"
    ) < names.index("Obtain short-lived Azure token through OIDC")
    assert names.index("Install pinned Poetry") < names.index(
        "Set up Python 3.13 and restore Poetry environment"
    )
    assert names.index(
        "Create deployment-specific rate card before Azure login"
    ) < names.index("Obtain short-lived Azure token through OIDC")
    assert names.index("Validate Azure bindings before Azure login") < names.index(
        "Obtain short-lived Azure token through OIDC"
    )
    assert names.index("Calibrate the independent judge") < names.index(
        "Run weekly real-model QA"
    )
    assert names.index("Verify Azure deployment model bindings") < names.index(
        "Calibrate the independent judge"
    )
    steps = workflow["jobs"]["quality-assurance"]["steps"]
    calibration = next(
        step for step in steps if step.get("name") == "Calibrate the independent judge"
    )
    plan = next(
        step for step in steps if step.get("name") == "Refuse an unsafe cost plan"
    )
    run = next(step for step in steps if step.get("name") == "Run weekly real-model QA")
    assert "--max-cost-usd 0.32" in calibration["run"]
    assert "--development-budget-usd 21" in calibration["run"]
    assert "--deployment-verification qa-results/deployments.json" in calibration["run"]
    assert "--development-budget-usd 21" in plan["run"]
    assert "--transient-retries 1" in plan["run"]
    assert "--uplift-percent 0" in plan["run"]
    assert "--max-cost-usd 20.51" in run["run"]
    assert "--development-budget-usd 21" in run["run"]
    assert "--transient-retries 1" in run["run"]
    assert "--uplift-percent 0" in run["run"]
    assert "--deployment-verification qa-results/deployments.json" in run["run"]

    install_poetry = next(
        step for step in steps if step.get("name") == "Install pinned Poetry"
    )
    setup_python = next(
        step
        for step in steps
        if step.get("name") == "Set up Python 3.13 and restore Poetry environment"
    )
    assert install_poetry["run"] == "pipx install poetry==2.4.1"
    assert setup_python["with"]["cache"] == "poetry"
    assert setup_python["with"]["cache-dependency-path"] == "iris/poetry.lock"


def test_sensitive_qa_paths_have_codeowners():
    codeowners = (REPO_ROOT / ".github" / "CODEOWNERS").read_text()
    assert "/.github/workflows/iris_qa_weekly.yml" in codeowners
    assert "/iris/src/iris/qa/" in codeowners
    assert "/iris/qa/baseline.json" in codeowners


def test_codeowners_file_self_protection_has_last_match_precedence():
    lines = [
        line.strip()
        for line in (REPO_ROOT / ".github" / "CODEOWNERS").read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]

    # Both "*" and the exact rule match .github/CODEOWNERS. GitHub applies the
    # last matching pattern, so the exact owner must occur after the wildcard.
    assert lines.index("/.github/CODEOWNERS @bassner") > next(
        index for index, line in enumerate(lines) if line.startswith("* ")
    )
