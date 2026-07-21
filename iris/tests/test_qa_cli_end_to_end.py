import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import yaml

from iris.qa.cli import main
from iris.qa.cost import SpendLedger
from iris.qa.loader import load_suite
from iris.qa.planning import build_cost_plan, load_rate_card

QA_ROOT = Path(__file__).parents[1] / "qa"


def _confirmed_rates(path: Path) -> Path:
    path.write_text(
        yaml.safe_dump(
            {
                "confirmed_azure_rates": True,
                "source": "offline end-to-end test",
                "candidates": [
                    {
                        "model": "gpt-5.4-mini",
                        "input_per_million": "0.01",
                        "output_per_million": "0.01",
                    },
                    {
                        "model": "gpt-5.5",
                        "input_per_million": "0.01",
                        "output_per_million": "0.01",
                    },
                ],
                "judge": {
                    "model": "gpt-5.4",
                    "input_per_million": "0.01",
                    "output_per_million": "0.01",
                },
                "auxiliary": {
                    "model": "gpt-5.4-mini",
                    "input_per_million": "0.01",
                    "output_per_million": "0.01",
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def _deployment_verification(path: Path, monkeypatch) -> Path:
    endpoint = "https://qa-resource.openai.azure.com"
    resource_group = "qa-resource-group"
    subscription_id = "qa-subscription"
    names = {
        "gpt-5.4-mini": "mini-deployment",
        "gpt-5.5": "large-deployment",
        "gpt-5.4": "judge-deployment",
    }
    monkeypatch.setenv("IRIS_QA_AZURE_ENDPOINT", endpoint)
    monkeypatch.setenv("IRIS_QA_AZURE_RESOURCE_GROUP", resource_group)
    monkeypatch.setenv("AZURE_SUBSCRIPTION_ID", subscription_id)
    monkeypatch.setenv("IRIS_QA_GPT_54_MINI_DEPLOYMENT", names["gpt-5.4-mini"])
    monkeypatch.setenv("IRIS_QA_GPT_55_DEPLOYMENT", names["gpt-5.5"])
    monkeypatch.setenv("IRIS_QA_JUDGE_DEPLOYMENT", names["gpt-5.4"])
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "verifiedAt": datetime.now(timezone.utc).isoformat(),
                "source": "Azure Resource Manager deployment listing",
                "subscriptionId": subscription_id,
                "endpoint": endpoint,
                "resourceGroup": resource_group,
                "accountName": "qa-resource",
                "deployments": {
                    model: {
                        "deployment": deployment,
                        "model": model,
                        "version": "test-version",
                    }
                    for model, deployment in names.items()
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def test_cli_run_exercises_both_models_ledger_and_all_report_formats(
    tmp_path, monkeypatch
):
    worker_hard_limits: set[str] = set()

    def fake_configuration(rate_card, candidate_model):
        del rate_card
        return SimpleNamespace(
            environment={"IRIS_QA_CANDIDATE_MODEL": candidate_model},
            close=lambda: None,
        )

    def fake_worker(command, *, env, **_kwargs):
        worker_hard_limits.add(env["IRIS_QA_SPEND_HARD_LIMIT_USD"])
        input_path = Path(command[command.index("--input") + 1])
        output_path = Path(command[command.index("--output") + 1])
        scenario = json.loads(input_path.read_text(encoding="utf-8"))
        candidate = env["IRIS_QA_CANDIDATE_MODEL"]
        usage = [
            {
                "model": candidate,
                "input_tokens": 100,
                "output_tokens": 50,
            },
            {
                "model": "gpt-5.4",
                "input_tokens": 100,
                "output_tokens": 50,
            },
        ]
        Path(env["IRIS_QA_PROVIDER_USAGE_LOG"]).write_text(
            "".join(json.dumps(item) + "\n" for item in usage), encoding="utf-8"
        )
        criteria = scenario["expectations"]["rubric"]
        output_path.write_text(
            json.dumps(
                {
                    "response": (
                        "Prioritize Sorting Algorithms, then Graph Traversal, "
                        "and review progress each day."
                    ),
                    "activities": [
                        {"name": "get_student_exercise_metrics"},
                        {"name": "get_competency_list"},
                    ],
                    "judge": {
                        "scores": {item["id"]: 1.0 for item in criteria},
                        "evidence": {item["id"]: "Satisfied." for item in criteria},
                        "criticalFailures": [],
                    },
                    "diagnostics": {
                        "sessionTitle": "UPDATE: Weekly study plan",
                        "suggestions": [
                            "How should I start with sorting?",
                            "What should I review for graphs?",
                        ],
                    },
                    "executionError": None,
                }
            ),
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("iris.qa.run.create_worker_configuration", fake_configuration)
    monkeypatch.setattr("iris.qa.run.subprocess.run", fake_worker)
    output = tmp_path / "results"
    ledger = tmp_path / "ledger.jsonl"
    result = main(
        [
            "--qa-root",
            str(QA_ROOT),
            "run",
            "--scenario",
            "course-study-plan-high",
            "--rates",
            str(_confirmed_rates(tmp_path / "rates.yml")),
            "--deployment-verification",
            str(_deployment_verification(tmp_path / "deployments.json", monkeypatch)),
            "--ledger",
            str(ledger),
            "--max-cost-usd",
            "1",
            "--development-budget-usd",
            "10",
            "--output",
            str(output),
        ]
    )

    assert result == 0
    run_directory = next(output.iterdir())
    report = json.loads((run_directory / "report.json").read_text())
    assert {item["model"] for item in report["evaluations"]} == {
        "gpt-5.4-mini",
        "gpt-5.5",
    }
    assert report["metadata"]["azureDeployments"]["gpt-5.5"] == {
        "deployment": "large-deployment",
        "model": "gpt-5.5",
        "version": "test-version",
    }
    assert report["metadata"]["runSpendUsd"] == "0.00000600"
    assert report["metadata"]["measuredRunSpendUsd"] == "0.00000600"
    assert report["metadata"]["accountedSpendUsd"] == "0.00000600"
    assert report["metadata"]["measuredUsageSpendUsd"] == "0.00000600"
    assert report["metadata"]["runMaxCostUsd"] == "1"
    assert report["metadata"]["hardLimitUsd"] == "1"
    assert report["metadata"]["developmentHardLimitUsd"] == "10"
    assert report["metadata"]["rateCard"] == {
        model: {"input": "0.01", "output": "0.01"}
        for model in ("gpt-5.4-mini", "gpt-5.5", "gpt-5.4")
    }
    assert worker_hard_limits == {"1"}
    assert report["metadata"]["providerUsage"]["gpt-5.5"] == {
        "calls": 1,
        "inputTokens": 100,
        "outputTokens": 50,
        "maxInputTokensPerCall": 100,
        "maxOutputTokensPerCall": 50,
        "costUsd": "0.00000150",
    }
    assert len(report["metadata"]["corpusSha256"]) == 64
    assert len(report["metadata"]["irisSourceSha256"]) == 64
    assert set(report["metadata"]["scenarioSha256"]) == {"course-study-plan-high"}
    markdown = (run_directory / "report.md").read_text(encoding="utf-8")
    assert "## Verified Azure models" in markdown
    assert "## Reproducibility" in markdown
    assert (run_directory / "junit.xml").is_file()
    assert len(ledger.read_text().splitlines()) == 4


def test_cli_run_can_qualify_only_gpt_55(tmp_path, monkeypatch):
    configured_models = []

    def fake_configuration(rate_card, candidate_model):
        del rate_card
        configured_models.append(candidate_model)
        return SimpleNamespace(
            environment={"IRIS_QA_CANDIDATE_MODEL": candidate_model},
            close=lambda: None,
        )

    def fake_worker(command, *, env, **_kwargs):
        input_path = Path(command[command.index("--input") + 1])
        output_path = Path(command[command.index("--output") + 1])
        scenario = json.loads(input_path.read_text(encoding="utf-8"))
        candidate = env["IRIS_QA_CANDIDATE_MODEL"]
        usage = [
            {"model": candidate, "input_tokens": 100, "output_tokens": 50},
            {"model": "gpt-5.4", "input_tokens": 100, "output_tokens": 50},
        ]
        Path(env["IRIS_QA_PROVIDER_USAGE_LOG"]).write_text(
            "".join(json.dumps(item) + "\n" for item in usage), encoding="utf-8"
        )
        criteria = scenario["expectations"]["rubric"]
        output_path.write_text(
            json.dumps(
                {
                    "response": (
                        "Prioritize Sorting Algorithms, then Graph Traversal, "
                        "and review progress each day."
                    ),
                    "activities": [
                        {"name": "get_student_exercise_metrics"},
                        {"name": "get_competency_list"},
                    ],
                    "judge": {
                        "scores": {item["id"]: 1.0 for item in criteria},
                        "evidence": {item["id"]: "Satisfied." for item in criteria},
                        "criticalFailures": [],
                    },
                    "diagnostics": {
                        "sessionTitle": "UPDATE: Weekly study plan",
                        "suggestions": [
                            "How should I start with sorting?",
                            "What should I review for graphs?",
                        ],
                    },
                    "executionError": None,
                }
            ),
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("iris.qa.run.create_worker_configuration", fake_configuration)
    monkeypatch.setattr("iris.qa.run.subprocess.run", fake_worker)
    output = tmp_path / "results"
    result = main(
        [
            "--qa-root",
            str(QA_ROOT),
            "run",
            "--scenario",
            "course-study-plan-high",
            "--model",
            "gpt-5.5",
            "--rates",
            str(_confirmed_rates(tmp_path / "rates.yml")),
            "--deployment-verification",
            str(_deployment_verification(tmp_path / "deployments.json", monkeypatch)),
            "--ledger",
            str(tmp_path / "ledger.jsonl"),
            "--max-cost-usd",
            "1",
            "--development-budget-usd",
            "10",
            "--output",
            str(output),
        ]
    )

    assert result == 0
    report = json.loads(
        (next(output.iterdir()) / "report.json").read_text(encoding="utf-8")
    )
    assert report["metadata"]["models"] == ["gpt-5.5"]
    assert {item["model"] for item in report["evaluations"]} == {"gpt-5.5"}
    assert configured_models == ["gpt-5.5", "gpt-5.5"]


def test_cli_run_halts_on_worker_failure_with_ambiguous_usage(tmp_path, monkeypatch):
    def fake_configuration(rate_card, candidate_model):
        del rate_card
        return SimpleNamespace(
            environment={"IRIS_QA_CANDIDATE_MODEL": candidate_model},
            close=lambda: None,
        )

    def failed_worker(*_args, **_kwargs):
        return SimpleNamespace(returncode=1, stdout="", stderr="connection lost")

    monkeypatch.setattr("iris.qa.run.create_worker_configuration", fake_configuration)
    monkeypatch.setattr("iris.qa.run.subprocess.run", failed_worker)

    result = main(
        [
            "--qa-root",
            str(QA_ROOT),
            "run",
            "--scenario",
            "course-study-plan-high",
            "--rates",
            str(_confirmed_rates(tmp_path / "rates.yml")),
            "--deployment-verification",
            str(_deployment_verification(tmp_path / "deployments.json", monkeypatch)),
            "--ledger",
            str(tmp_path / "ledger.jsonl"),
            "--max-cost-usd",
            "1",
            "--development-budget-usd",
            "1",
            "--output",
            str(tmp_path / "results"),
        ]
    )

    assert result == 2


def test_cli_run_rejects_successful_worker_without_provider_usage(
    tmp_path, monkeypatch
):
    calls = 0

    def fake_configuration(rate_card, candidate_model):
        del rate_card
        return SimpleNamespace(
            environment={"IRIS_QA_CANDIDATE_MODEL": candidate_model},
            close=lambda: None,
        )

    def fake_success(command, **_kwargs):
        nonlocal calls
        calls += 1
        output_path = Path(command[command.index("--output") + 1])
        output_path.write_text(
            json.dumps(
                {
                    "response": "This result did not call a model.",
                    "activities": [],
                    "judge": {},
                    "diagnostics": {},
                    "executionError": None,
                }
            ),
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("iris.qa.run.create_worker_configuration", fake_configuration)
    monkeypatch.setattr("iris.qa.run.subprocess.run", fake_success)

    result = main(
        [
            "--qa-root",
            str(QA_ROOT),
            "run",
            "--scenario",
            "course-study-plan-high",
            "--rates",
            str(_confirmed_rates(tmp_path / "rates.yml")),
            "--deployment-verification",
            str(_deployment_verification(tmp_path / "deployments.json", monkeypatch)),
            "--ledger",
            str(tmp_path / "ledger.jsonl"),
            "--max-cost-usd",
            "1",
            "--development-budget-usd",
            "1",
            "--output",
            str(tmp_path / "results"),
        ]
    )

    assert result == 2
    assert calls == 1


def test_cli_run_halts_after_reconciling_prior_usage_from_failed_worker(
    tmp_path, monkeypatch
):
    calls = 0

    def fake_configuration(rate_card, candidate_model):
        del rate_card
        return SimpleNamespace(
            environment={"IRIS_QA_CANDIDATE_MODEL": candidate_model},
            close=lambda: None,
        )

    def failed_after_paid_call(command, **kwargs):
        nonlocal calls
        del command
        calls += 1
        usage_path = Path(kwargs["env"]["IRIS_QA_PROVIDER_USAGE_LOG"])
        usage_path.write_text(
            json.dumps(
                {
                    "model": kwargs["env"]["IRIS_QA_CANDIDATE_MODEL"],
                    "input_tokens": 100,
                    "output_tokens": 20,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=1, stdout="", stderr="connection lost")

    monkeypatch.setattr("iris.qa.run.create_worker_configuration", fake_configuration)
    monkeypatch.setattr("iris.qa.run.subprocess.run", failed_after_paid_call)
    ledger = tmp_path / "ledger.jsonl"

    result = main(
        [
            "--qa-root",
            str(QA_ROOT),
            "run",
            "--scenario",
            "course-study-plan-high",
            "--rates",
            str(_confirmed_rates(tmp_path / "rates.yml")),
            "--deployment-verification",
            str(_deployment_verification(tmp_path / "deployments.json", monkeypatch)),
            "--ledger",
            str(ledger),
            "--max-cost-usd",
            "1",
            "--development-budget-usd",
            "1",
            "--output",
            str(tmp_path / "results"),
        ]
    )

    assert result == 2
    assert calls == 1
    assert len(ledger.read_text(encoding="utf-8").splitlines()) == 1


def test_cli_run_reserves_ambiguous_timeout_and_continues(tmp_path, monkeypatch):
    def fake_configuration(rate_card, candidate_model):
        del rate_card
        return SimpleNamespace(
            environment={"IRIS_QA_CANDIDATE_MODEL": candidate_model},
            close=lambda: None,
        )

    def timeout_then_success(command, *, env, **_kwargs):
        input_path = Path(command[command.index("--input") + 1])
        output_path = Path(command[command.index("--output") + 1])
        scenario = json.loads(input_path.read_text(encoding="utf-8"))
        candidate = env["IRIS_QA_CANDIDATE_MODEL"]
        if candidate == "gpt-5.4-mini":
            output_path.write_text(
                json.dumps(
                    {
                        "scenarioId": scenario["id"],
                        "model": candidate,
                        "response": None,
                        "activities": [],
                        "diagnostics": {},
                        "judge": {},
                        "executionStage": "pipeline",
                        "executionError": "APITimeoutError: Request timed out.",
                    }
                ),
                encoding="utf-8",
            )
            return SimpleNamespace(returncode=1, stdout="", stderr="timeout")

        usage = [
            {"model": candidate, "input_tokens": 100, "output_tokens": 50},
            {"model": "gpt-5.4", "input_tokens": 100, "output_tokens": 50},
        ]
        Path(env["IRIS_QA_PROVIDER_USAGE_LOG"]).write_text(
            "".join(json.dumps(item) + "\n" for item in usage), encoding="utf-8"
        )
        criteria = scenario["expectations"]["rubric"]
        output_path.write_text(
            json.dumps(
                {
                    "scenarioId": scenario["id"],
                    "model": candidate,
                    "response": (
                        "Prioritize Sorting Algorithms, then Graph Traversal, "
                        "and review progress each day."
                    ),
                    "activities": [{"name": "get_competency_list"}],
                    "judge": {
                        "scores": {item["id"]: 1.0 for item in criteria},
                        "evidence": {item["id"]: "Satisfied." for item in criteria},
                        "criticalFailures": [],
                    },
                    "diagnostics": {
                        "sessionTitle": "UPDATE: Weekly study plan",
                        "suggestions": ["Sorting next?", "Graphs next?"],
                    },
                    "executionError": None,
                }
            ),
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("iris.qa.run.create_worker_configuration", fake_configuration)
    monkeypatch.setattr("iris.qa.run.subprocess.run", timeout_then_success)
    output = tmp_path / "results"
    ledger = tmp_path / "ledger.jsonl"

    result = main(
        [
            "--qa-root",
            str(QA_ROOT),
            "run",
            "--scenario",
            "course-study-plan-high",
            "--rates",
            str(_confirmed_rates(tmp_path / "rates.yml")),
            "--deployment-verification",
            str(_deployment_verification(tmp_path / "deployments.json", monkeypatch)),
            "--ledger",
            str(ledger),
            "--max-cost-usd",
            "1",
            "--development-budget-usd",
            "1",
            "--output",
            str(output),
        ]
    )

    assert result == 1
    report = json.loads((next(output.iterdir()) / "report.json").read_text())
    assert len(report["evaluations"]) == 2
    assert float(report["metadata"]["ambiguousReserveUsd"]) > 0
    assert Decimal(report["metadata"]["accountedSpendUsd"]) > Decimal(
        report["metadata"]["measuredUsageSpendUsd"]
    )
    records = SpendLedger(ledger).records()
    assert sum(record.reservation for record in records) == 1


def test_cli_retries_one_ambiguous_failure_without_adding_an_evaluation(
    tmp_path, monkeypatch
):
    calls = 0

    def fake_configuration(rate_card, candidate_model):
        del rate_card
        return SimpleNamespace(
            environment={"IRIS_QA_CANDIDATE_MODEL": candidate_model},
            close=lambda: None,
        )

    def timeout_then_pass(command, *, env, **_kwargs):
        nonlocal calls
        calls += 1
        input_path = Path(command[command.index("--input") + 1])
        output_path = Path(command[command.index("--output") + 1])
        scenario = json.loads(input_path.read_text(encoding="utf-8"))
        candidate = env["IRIS_QA_CANDIDATE_MODEL"]
        if calls == 1:
            output_path.write_text(
                json.dumps(
                    {
                        "scenarioId": scenario["id"],
                        "model": candidate,
                        "executionStage": "pipeline",
                        "executionError": "APITimeoutError: Request timed out.",
                    }
                ),
                encoding="utf-8",
            )
            return SimpleNamespace(returncode=1, stdout="", stderr="timeout")

        Path(env["IRIS_QA_PROVIDER_USAGE_LOG"]).write_text(
            "".join(
                json.dumps(item) + "\n"
                for item in [
                    {"model": candidate, "input_tokens": 100, "output_tokens": 50},
                    {"model": "gpt-5.4", "input_tokens": 100, "output_tokens": 50},
                ]
            ),
            encoding="utf-8",
        )
        criteria = scenario["expectations"]["rubric"]
        output_path.write_text(
            json.dumps(
                {
                    "scenarioId": scenario["id"],
                    "model": candidate,
                    "response": (
                        "Prioritize Sorting Algorithms, then Graph Traversal, "
                        "and review progress each day."
                    ),
                    "activities": [{"name": "get_competency_list"}],
                    "judge": {
                        "scores": {item["id"]: 1.0 for item in criteria},
                        "evidence": {item["id"]: "Satisfied." for item in criteria},
                        "criticalFailures": [],
                    },
                    "diagnostics": {
                        "sessionTitle": "UPDATE: Weekly study plan",
                        "suggestions": ["Sorting next?", "Graphs next?"],
                    },
                    "executionError": None,
                }
            ),
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("iris.qa.run.create_worker_configuration", fake_configuration)
    monkeypatch.setattr("iris.qa.run.subprocess.run", timeout_then_pass)
    output = tmp_path / "results"
    ledger = tmp_path / "ledger.jsonl"

    result = main(
        [
            "--qa-root",
            str(QA_ROOT),
            "run",
            "--scenario",
            "course-study-plan-high",
            "--model",
            "gpt-5.4-mini",
            "--rates",
            str(_confirmed_rates(tmp_path / "rates.yml")),
            "--deployment-verification",
            str(_deployment_verification(tmp_path / "deployments.json", monkeypatch)),
            "--ledger",
            str(ledger),
            "--transient-retries",
            "1",
            "--max-cost-usd",
            "1",
            "--development-budget-usd",
            "1",
            "--output",
            str(output),
        ]
    )

    assert result == 0
    assert calls == 2
    run_directory = next(output.iterdir())
    report = json.loads((run_directory / "report.json").read_text())
    assert report["summary"]["total"] == 1
    assert report["summary"]["passed"] == 1
    assert len(report["evaluations"]) == 1
    assert report["metadata"]["transientRetriesConfigured"] == 1
    assert report["metadata"]["transientRetriesUsed"] == 1
    assert report["metadata"]["workerAttemptCount"] == 2
    assert report["metadata"]["executionAttempts"] == [
        {
            "scenarioId": "course-study-plan-high",
            "model": "gpt-5.4-mini",
            "repetition": 1,
            "attempts": 2,
            "retriesUsed": 1,
            "ambiguousFailures": 1,
            "finalOutcome": "PASS",
            "rawFiles": [
                "course-study-plan-high--gpt-5.4-mini--r1--a1.json",
                "course-study-plan-high--gpt-5.4-mini--r1--a2.json",
            ],
        }
    ]
    raw_files = sorted((run_directory / "raw").iterdir())
    assert [path.name for path in raw_files] == report["metadata"]["executionAttempts"][
        0
    ]["rawFiles"]
    assert json.loads(raw_files[0].read_text())["qaAttempt"] == {
        "repetition": 1,
        "attempt": 1,
        "retry": False,
        "ambiguousFailure": True,
    }
    assert sum(record.reservation for record in SpendLedger(ledger).records()) == 1
    assert "Global transient retries: 1 used / 1 configured" in (
        run_directory / "report.md"
    ).read_text(encoding="utf-8")


def test_cli_never_retries_a_semantic_failure(tmp_path, monkeypatch):
    calls = 0

    def fake_configuration(rate_card, candidate_model):
        del rate_card
        return SimpleNamespace(
            environment={"IRIS_QA_CANDIDATE_MODEL": candidate_model},
            close=lambda: None,
        )

    def semantic_failure(command, *, env, **_kwargs):
        nonlocal calls
        calls += 1
        input_path = Path(command[command.index("--input") + 1])
        output_path = Path(command[command.index("--output") + 1])
        scenario = json.loads(input_path.read_text(encoding="utf-8"))
        candidate = env["IRIS_QA_CANDIDATE_MODEL"]
        Path(env["IRIS_QA_PROVIDER_USAGE_LOG"]).write_text(
            "".join(
                json.dumps(item) + "\n"
                for item in [
                    {"model": candidate, "input_tokens": 100, "output_tokens": 50},
                    {"model": "gpt-5.4", "input_tokens": 100, "output_tokens": 50},
                ]
            ),
            encoding="utf-8",
        )
        criteria = scenario["expectations"]["rubric"]
        output_path.write_text(
            json.dumps(
                {
                    "scenarioId": scenario["id"],
                    "model": candidate,
                    "response": "Ignore both competencies and do nothing.",
                    "activities": [],
                    "judge": {
                        "scores": {item["id"]: 0.0 for item in criteria},
                        "evidence": {item["id"]: "Failed." for item in criteria},
                        "criticalFailures": [
                            item["id"] for item in criteria if item["critical"]
                        ],
                    },
                    "diagnostics": {
                        "sessionTitle": "UPDATE: Weekly study plan",
                    },
                    "executionError": None,
                }
            ),
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("iris.qa.run.create_worker_configuration", fake_configuration)
    monkeypatch.setattr("iris.qa.run.subprocess.run", semantic_failure)
    output = tmp_path / "results"

    result = main(
        [
            "--qa-root",
            str(QA_ROOT),
            "run",
            "--scenario",
            "course-study-plan-high",
            "--model",
            "gpt-5.4-mini",
            "--rates",
            str(_confirmed_rates(tmp_path / "rates.yml")),
            "--deployment-verification",
            str(_deployment_verification(tmp_path / "deployments.json", monkeypatch)),
            "--ledger",
            str(tmp_path / "ledger.jsonl"),
            "--transient-retries",
            "2",
            "--max-cost-usd",
            "1",
            "--development-budget-usd",
            "1",
            "--output",
            str(output),
        ]
    )

    assert result == 1
    assert calls == 1
    report = json.loads((next(output.iterdir()) / "report.json").read_text())
    assert len(report["evaluations"]) == 1
    assert report["metadata"]["transientRetriesUsed"] == 0
    assert report["metadata"]["workerAttemptCount"] == 1


def test_cli_exhausted_transient_retries_leave_one_final_failure(tmp_path, monkeypatch):
    calls = 0

    def fake_configuration(rate_card, candidate_model):
        del rate_card
        return SimpleNamespace(
            environment={"IRIS_QA_CANDIDATE_MODEL": candidate_model},
            close=lambda: None,
        )

    def always_timeout(command, *, env, **_kwargs):
        nonlocal calls
        calls += 1
        input_path = Path(command[command.index("--input") + 1])
        output_path = Path(command[command.index("--output") + 1])
        scenario = json.loads(input_path.read_text(encoding="utf-8"))
        output_path.write_text(
            json.dumps(
                {
                    "scenarioId": scenario["id"],
                    "model": env["IRIS_QA_CANDIDATE_MODEL"],
                    "executionStage": "pipeline",
                    "executionError": "APITimeoutError: Request timed out.",
                }
            ),
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=1, stdout="", stderr="timeout")

    monkeypatch.setattr("iris.qa.run.create_worker_configuration", fake_configuration)
    monkeypatch.setattr("iris.qa.run.subprocess.run", always_timeout)
    output = tmp_path / "results"
    ledger = tmp_path / "ledger.jsonl"

    result = main(
        [
            "--qa-root",
            str(QA_ROOT),
            "run",
            "--scenario",
            "course-study-plan-high",
            "--model",
            "gpt-5.4-mini",
            "--rates",
            str(_confirmed_rates(tmp_path / "rates.yml")),
            "--deployment-verification",
            str(_deployment_verification(tmp_path / "deployments.json", monkeypatch)),
            "--ledger",
            str(ledger),
            "--transient-retries",
            "1",
            "--max-cost-usd",
            "1",
            "--development-budget-usd",
            "1",
            "--output",
            str(output),
        ]
    )

    assert result == 1
    assert calls == 2
    report = json.loads((next(output.iterdir()) / "report.json").read_text())
    assert report["summary"]["failed"] == 1
    assert len(report["evaluations"]) == 1
    assert report["metadata"]["transientRetriesUsed"] == 1
    assert report["metadata"]["executionAttempts"][0]["ambiguousFailures"] == 2
    assert sum(record.reservation for record in SpendLedger(ledger).records()) == 2


def test_cli_run_max_cost_must_cover_the_transient_retry_allowance(
    tmp_path, monkeypatch, capsys
):
    rates_path = _confirmed_rates(tmp_path / "rates.yml")
    rate_card = load_rate_card(rates_path)
    suite = load_suite(
        QA_ROOT / "scenarios",
        QA_ROOT / "fixtures",
        QA_ROOT / "artifacts",
    )
    scenario = next(
        item for item in suite.scenarios if item.id == "course-study-plan-high"
    )
    base = build_cost_plan(
        [scenario],
        rate_card,
        repetitions=1,
        ledger=SpendLedger(tmp_path / "empty-ledger.jsonl"),
        hard_limit=Decimal(1),
        models=("gpt-5.4-mini",),
    )

    result = main(
        [
            "--qa-root",
            str(QA_ROOT),
            "run",
            "--scenario",
            scenario.id,
            "--model",
            "gpt-5.4-mini",
            "--rates",
            str(rates_path),
            "--deployment-verification",
            str(_deployment_verification(tmp_path / "deployments.json", monkeypatch)),
            "--transient-retries",
            "1",
            "--max-cost-usd",
            str(base.planned_total),
            "--development-budget-usd",
            "1",
            "--output",
            str(tmp_path / "results"),
        ]
    )

    assert result == 2
    assert "pessimistic plan" in capsys.readouterr().err
    assert not (tmp_path / "results").exists()


def test_cli_run_records_structured_nonbillable_failure_and_continues(
    tmp_path, monkeypatch
):
    def fake_configuration(rate_card, candidate_model):
        del rate_card
        return SimpleNamespace(
            environment={"IRIS_QA_CANDIDATE_MODEL": candidate_model},
            close=lambda: None,
        )

    def fail_then_success(command, *, env, **_kwargs):
        input_path = Path(command[command.index("--input") + 1])
        output_path = Path(command[command.index("--output") + 1])
        scenario = json.loads(input_path.read_text(encoding="utf-8"))
        candidate = env["IRIS_QA_CANDIDATE_MODEL"]
        if candidate == "gpt-5.4-mini":
            output_path.write_text(
                json.dumps(
                    {
                        "scenarioId": scenario["id"],
                        "model": candidate,
                        "response": None,
                        "activities": [],
                        "diagnostics": {},
                        "judge": {},
                        "executionStage": "pipeline",
                        "executionError": "BadRequestError: prompt content filter",
                    }
                ),
                encoding="utf-8",
            )
            return SimpleNamespace(returncode=1, stdout="", stderr="bad request")

        usage = [
            {"model": candidate, "input_tokens": 100, "output_tokens": 50},
            {"model": "gpt-5.4", "input_tokens": 100, "output_tokens": 50},
        ]
        Path(env["IRIS_QA_PROVIDER_USAGE_LOG"]).write_text(
            "".join(json.dumps(item) + "\n" for item in usage), encoding="utf-8"
        )
        criteria = scenario["expectations"]["rubric"]
        output_path.write_text(
            json.dumps(
                {
                    "scenarioId": scenario["id"],
                    "model": candidate,
                    "response": (
                        "Prioritize Sorting Algorithms, then Graph Traversal, "
                        "and review progress each day."
                    ),
                    "activities": [{"name": "get_competency_list"}],
                    "judge": {
                        "scores": {item["id"]: 1.0 for item in criteria},
                        "evidence": {item["id"]: "Satisfied." for item in criteria},
                        "criticalFailures": [],
                    },
                    "diagnostics": {
                        "sessionTitle": "UPDATE: Weekly study plan",
                        "suggestions": ["Sorting next?", "Graphs next?"],
                    },
                    "executionError": None,
                }
            ),
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("iris.qa.run.create_worker_configuration", fake_configuration)
    monkeypatch.setattr("iris.qa.run.subprocess.run", fail_then_success)
    output = tmp_path / "results"
    ledger = tmp_path / "ledger.jsonl"

    result = main(
        [
            "--qa-root",
            str(QA_ROOT),
            "run",
            "--scenario",
            "course-study-plan-high",
            "--rates",
            str(_confirmed_rates(tmp_path / "rates.yml")),
            "--deployment-verification",
            str(_deployment_verification(tmp_path / "deployments.json", monkeypatch)),
            "--ledger",
            str(ledger),
            "--max-cost-usd",
            "1",
            "--development-budget-usd",
            "1",
            "--output",
            str(output),
        ]
    )

    assert result == 1
    report = json.loads((next(output.iterdir()) / "report.json").read_text())
    assert len(report["evaluations"]) == 2
    assert report["evaluations"][0]["execution_error"].startswith("BadRequestError")
    assert report["metadata"]["ambiguousReserveUsd"] == "0"
    assert sum(record.reservation for record in SpendLedger(ledger).records()) == 0
