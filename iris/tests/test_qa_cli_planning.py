from decimal import Decimal
from pathlib import Path

import yaml

from iris.qa.cli import main
from iris.qa.cost import SpendLedger
from iris.qa.loader import load_suite
from iris.qa.planning import build_cost_plan, load_rate_card, worker_cost_reserve

QA_ROOT = Path(__file__).parents[1] / "qa"


def _rates(tmp_path: Path, *, confirmed: bool = True) -> Path:
    path = tmp_path / "rates.yml"
    path.write_text(
        yaml.safe_dump(
            {
                "confirmed_azure_rates": confirmed,
                "source": "unit test",
                "candidates": [
                    {
                        "model": "gpt-5.4-mini",
                        "input_per_million": "0.01",
                        "output_per_million": "0.01",
                    },
                    {
                        "model": "gpt-5.5",
                        "input_per_million": "0.02",
                        "output_per_million": "0.02",
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


def test_validate_and_list_commands(capsys):
    assert main(["--qa-root", str(QA_ROOT), "validate"]) == 0
    assert "50 scenarios are valid" in capsys.readouterr().out
    assert main(["--qa-root", str(QA_ROOT), "list", "--profile", "smoke"]) == 0
    assert "7 selected scenarios" in capsys.readouterr().out


def test_doctor_validates_azure_bindings_without_a_request(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("IRIS_QA_AZURE_ENDPOINT", "https://qa.openai.azure.com")
    monkeypatch.setenv("IRIS_QA_AZURE_AUTH_MODE", "azure_ad")
    monkeypatch.setenv("IRIS_QA_GPT_54_MINI_DEPLOYMENT", "mini")
    monkeypatch.setenv("IRIS_QA_GPT_55_DEPLOYMENT", "large")
    monkeypatch.setenv("IRIS_QA_JUDGE_DEPLOYMENT", "judge")

    assert main(["doctor", "--rates", str(_rates(tmp_path))]) == 0
    assert "no credential or model request" in capsys.readouterr().out


def test_plan_requires_confirmed_rates(tmp_path, capsys):
    result = main(
        [
            "--qa-root",
            str(QA_ROOT),
            "plan",
            "--profile",
            "smoke",
            "--rates",
            str(_rates(tmp_path, confirmed=False)),
            "--ledger",
            str(tmp_path / "ledger.jsonl"),
        ]
    )
    assert result == 2
    assert "not confirmed" in capsys.readouterr().err


def test_plan_rejects_zero_rate_in_a_confirmed_card(tmp_path, capsys):
    rates = _rates(tmp_path)
    payload = yaml.safe_load(rates.read_text(encoding="utf-8"))
    payload["candidates"][0]["input_per_million"] = "0"
    rates.write_text(yaml.safe_dump(payload), encoding="utf-8")

    result = main(
        [
            "--qa-root",
            str(QA_ROOT),
            "plan",
            "--profile",
            "smoke",
            "--rates",
            str(rates),
            "--ledger",
            str(tmp_path / "ledger.jsonl"),
        ]
    )

    assert result == 2
    assert "Invalid model rate" in capsys.readouterr().err


def test_plan_rejects_auxiliary_prices_that_differ_from_the_shared_mini_deployment(
    tmp_path, capsys
):
    rates = _rates(tmp_path)
    payload = yaml.safe_load(rates.read_text(encoding="utf-8"))
    payload["auxiliary"]["output_per_million"] = "0.02"
    rates.write_text(yaml.safe_dump(payload), encoding="utf-8")

    result = main(
        [
            "--qa-root",
            str(QA_ROOT),
            "plan",
            "--profile",
            "smoke",
            "--rates",
            str(rates),
            "--ledger",
            str(tmp_path / "ledger.jsonl"),
        ]
    )

    assert result == 2
    assert "same Azure deployment" in capsys.readouterr().err


def test_plan_requires_a_confirmed_rate_source(tmp_path, capsys):
    rates = _rates(tmp_path)
    payload = yaml.safe_load(rates.read_text(encoding="utf-8"))
    payload["source"] = ""
    rates.write_text(yaml.safe_dump(payload), encoding="utf-8")

    result = main(
        [
            "--qa-root",
            str(QA_ROOT),
            "plan",
            "--profile",
            "smoke",
            "--rates",
            str(rates),
            "--ledger",
            str(tmp_path / "ledger.jsonl"),
        ]
    )

    assert result == 2
    assert "source of its confirmed Azure rates" in capsys.readouterr().err


def test_selection_refuses_an_empty_tag_filter(capsys):
    result = main(
        [
            "--qa-root",
            str(QA_ROOT),
            "list",
            "--tag",
            "does_not_exist",
        ]
    )

    assert result == 2
    assert "selection is empty" in capsys.readouterr().err


def test_plan_fits_and_refuses_hard_budget(tmp_path, capsys):
    rates = _rates(tmp_path)
    base = [
        "--qa-root",
        str(QA_ROOT),
        "plan",
        "--profile",
        "smoke",
        "--rates",
        str(rates),
        "--ledger",
        str(tmp_path / "ledger.jsonl"),
    ]
    assert main(base + ["--development-budget-usd", "30"]) == 0
    assert "READY" in capsys.readouterr().out
    assert main(base + ["--development-budget-usd", "0.001"]) == 2
    assert "REFUSED" in capsys.readouterr().out


def test_targeted_plan_includes_the_largest_runtime_worker_reserve(tmp_path, capsys):
    arguments = [
        "--qa-root",
        str(QA_ROOT),
        "plan",
        "--scenario",
        "course-three-mcqs-german-high",
        "--rates",
        str(_rates(tmp_path)),
        "--ledger",
        str(tmp_path / "ledger.jsonl"),
        "--development-budget-usd",
        "30",
    ]

    assert main(arguments) == 0
    output = capsys.readouterr().out
    assert "Runtime reserve floor" in output


def test_transient_retry_plan_uses_a_global_largest_worker_allowance(tmp_path, capsys):
    rate_card = load_rate_card(_rates(tmp_path))
    suite = load_suite(
        QA_ROOT / "scenarios",
        QA_ROOT / "fixtures",
        QA_ROOT / "artifacts",
    )
    scenarios = [
        scenario
        for scenario in suite.scenarios
        if scenario.id in {"course-study-plan-high", "course-three-mcqs-german-high"}
    ]
    ledger = SpendLedger(tmp_path / "ledger.jsonl")
    base = build_cost_plan(
        scenarios,
        rate_card,
        repetitions=1,
        ledger=ledger,
        hard_limit=Decimal(30),
    )
    retried = build_cost_plan(
        scenarios,
        rate_card,
        repetitions=1,
        transient_retries=2,
        ledger=ledger,
        hard_limit=Decimal(30),
    )
    largest_reserve = max(
        worker_cost_reserve(
            scenario,
            rate_card,
            candidate_models=(model,),
        )
        for scenario in scenarios
        for model in ("gpt-5.4-mini", "gpt-5.5")
    )

    assert retried.transient_retry_allowance == largest_reserve * 2
    assert retried.planned_total == base.planned_total + largest_reserve * 2

    result = main(
        [
            "--qa-root",
            str(QA_ROOT),
            "plan",
            "--scenario",
            "course-study-plan-high",
            "--rates",
            str(_rates(tmp_path)),
            "--transient-retries",
            "1",
            "--ledger",
            str(tmp_path / "cli-ledger.jsonl"),
        ]
    )
    assert result == 0
    output = capsys.readouterr().out
    assert "global transient retries=1" in output
    assert "Retry allowance" in output


def test_plan_can_qualify_one_candidate_without_charging_for_the_other(
    tmp_path, capsys
):
    result = main(
        [
            "--qa-root",
            str(QA_ROOT),
            "plan",
            "--profile",
            "smoke",
            "--model",
            "gpt-5.4-mini",
            "--rates",
            str(_rates(tmp_path)),
            "--ledger",
            str(tmp_path / "ledger.jsonl"),
        ]
    )

    assert result == 0
    output = capsys.readouterr().out
    assert "Candidate gpt-5.4-mini" in output
    assert "Candidate gpt-5.5" not in output


def test_plan_rejects_negative_safety_uplift(tmp_path, capsys):
    result = main(
        [
            "--qa-root",
            str(QA_ROOT),
            "plan",
            "--profile",
            "smoke",
            "--rates",
            str(_rates(tmp_path)),
            "--uplift-percent",
            "-10",
            "--ledger",
            str(tmp_path / "ledger.jsonl"),
        ]
    )

    assert result == 2
    assert "uplift percent" in capsys.readouterr().err


def test_plan_reports_invalid_decimal_without_a_traceback(tmp_path, capsys):
    result = main(
        [
            "--qa-root",
            str(QA_ROOT),
            "plan",
            "--profile",
            "smoke",
            "--rates",
            str(_rates(tmp_path)),
            "--development-budget-usd",
            "not-a-number",
            "--ledger",
            str(tmp_path / "ledger.jsonl"),
        ]
    )

    assert result == 2
    assert "must be a decimal number" in capsys.readouterr().err
