"""The shared chat rubric and the collect-now, judge-later workflow of the benchmark."""

import functools
import importlib
import json
import subprocess
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import yaml
from pydantic import ValidationError

# Establish the production package import order before importing DTOs.
importlib.import_module("iris.pipeline.pipeline")

from iris.pipeline.chat import chat_pipeline  # noqa: E402
from iris.qa.bootstrap import (  # noqa: E402
    apply_local_llm_config,
    create_worker_configuration,
)
from iris.qa.cost import ModelRate, SpendLedger  # noqa: E402
from iris.qa.evaluate import (  # noqa: E402
    CriterionResult,
    CriticalErrorResult,
    Rating,
    ScenarioEvaluation,
    evaluation_from_worker,
)
from iris.qa.external_judge import (  # noqa: E402
    KEY_FILE,
    export_judge_bundles,
    import_judgments,
)
from iris.qa.loader import _scenario_from_raw, load_suite  # noqa: E402
from iris.qa.planning import build_cost_plan, trial_reserve  # noqa: E402
from iris.qa.report import summarize  # noqa: E402
from iris.qa.rubric import (  # noqa: E402
    CHAT_MODE_USAGE_WEIGHTS,
    SHARED_CRITERIA,
    SHARED_CRITERION_IDS,
)
from iris.qa.run import COLLECTION_FILE, run_paid_suite  # noqa: E402
from iris.qa.schema import Criterion, Scenario, shared_criteria  # noqa: E402
from iris.qa.worker import JUDGE_SYSTEM_PROMPT, build_judge_request  # noqa: E402

QA_ROOT = Path(__file__).parents[1] / "qa"

REFERENCE = [
    "FACT: The failing test expects the list to be sorted before it is returned.",
    "NEED: The student needs to find where the order is lost.",
]


def _raw(**overrides):
    raw = {
        "id": "rubric-example",
        "title": "A rubric example",
        "description": "The answer should help the student take the next step.",
        "use_case": "chat",
        "mode": "COURSE_CHAT",
        "support_level": "moderate",
        "payload": {},
        "reference": REFERENCE,
        "critical_errors": ["The answer invents facts not in the evidence."],
    }
    raw.update(overrides)
    return raw


def _scenario(**overrides) -> Scenario:
    return _scenario_from_raw(_raw(**overrides), Path("."))


@functools.cache
def _suite():
    return load_suite(
        QA_ROOT / "scenarios", QA_ROOT / "fixtures", QA_ROOT / "artifacts"
    )


def _real_chat(count: int) -> list[Scenario]:
    chat = [item for item in _suite().scenarios if item.use_case.value == "chat"]
    return chat[:count]


def _tutor_suggestion() -> Scenario:
    return next(
        item for item in _suite().scenarios if item.use_case.value == "tutor_suggestion"
    )


@pytest.fixture(autouse=True)
def _no_llm_backed_sub_pipelines(monkeypatch):
    """Building the judge input renders the prompts, which needs no LLM clients."""
    for name in (
        "SessionTitleGenerationPipeline",
        "CitationPipeline",
        "InteractionSuggestionPipeline",
        "CodeFeedbackPipeline",
        "McqGenerationPipeline",
    ):
        monkeypatch.setattr(chat_pipeline, name, MagicMock())


@pytest.fixture(name="isolated_environment")
def _isolated_environment(monkeypatch):
    """Let a test load a local LLM config without leaking it into other tests."""
    for name in (
        "IRIS_QA_HELPER_ROUTE",
        "IRIS_QA_LOGOS_BASE_URL",
        "IRIS_QA_LOGOS_API_KEY",
        "IRIS_QA_GPT_6_LUNA_MODEL",
        "IRIS_QA_GPT_6_1_SOL_MODEL",
        "IRIS_QA_GPT_61_SOL_MODEL",
        "IRIS_QA_GPT_OSS_120B_MODEL",
    ):
        monkeypatch.setenv(name, "")


def test_shared_criteria_are_valid_and_cover_the_five_questions():
    assert SHARED_CRITERION_IDS == (
        "trustworthy",
        "moves-forward",
        "keeps-thinking",
        "easy-to-follow",
        "encouraging",
    )
    for item in SHARED_CRITERIA:
        Criterion.model_validate(item)
    assert sum(CHAT_MODE_USAGE_WEIGHTS.values()) == pytest.approx(1.0)


def test_chat_scenarios_get_the_shared_criteria_from_the_loader():
    scenario = _scenario()

    assert [item.id for item in scenario.criteria] == list(SHARED_CRITERION_IDS)
    assert all(item.guidance for item in scenario.criteria)


def test_chat_scenarios_cannot_bring_their_own_criteria():
    own = [
        {"id": f"own-{index}", "description": "A scenario specific criterion."}
        for index in range(3)
    ]

    with pytest.raises(ValidationError, match="shared rubric"):
        _scenario(criteria=own)


def test_chat_scenarios_need_reference_entries():
    with pytest.raises(ValidationError, match="reference"):
        _scenario(reference=[])
    with pytest.raises(ValidationError):
        _scenario(reference=["too short"])


def test_other_use_cases_keep_their_own_criteria():
    scenario = _tutor_suggestion()

    assert 3 <= len(scenario.criteria) <= 5
    assert not {item.id for item in scenario.criteria} & set(SHARED_CRITERION_IDS)


def test_judge_request_carries_reference_facts_and_criterion_guidance():
    scenario = _real_chat(1)[0]

    request = build_judge_request(scenario, "An answer.", [], {})

    assert request["referenceFacts"] == scenario.reference
    assert [item["id"] for item in request["criteria"]] == list(SHARED_CRITERION_IDS)
    assert all("guidance" in item for item in request["criteria"])
    assert "referenceFacts" in JUDGE_SYSTEM_PROMPT


def test_judge_request_of_other_use_cases_has_no_reference_or_guidance():
    request = build_judge_request(_tutor_suggestion(), "An answer.", [], {})

    assert "referenceFacts" not in request
    assert all("guidance" not in item for item in request["criteria"])


def _judgment(scenario: Scenario, rating: str = "achieved", *, present: bool = False):
    return {
        "criteria": [
            {"id": item.id, "rating": rating, "evidence": "Seen in the answer."}
            for item in scenario.criteria
        ],
        "criticalErrors": [
            {"description": error, "present": present, "evidence": "Checked."}
            for error in scenario.critical_errors
        ],
    }


def _evaluation(scenario: Scenario, model="m", *, ratings=None, errors=False):
    ratings = ratings or {}
    return ScenarioEvaluation(
        scenario_id=scenario.id,
        title=scenario.title,
        description=scenario.description,
        model=model,
        repetition=1,
        use_case=scenario.use_case.value,
        mode=scenario.mode,
        support_level=scenario.support_level,
        difficulty=scenario.difficulty,
        tags=[],
        response="answer",
        activities=[],
        criteria=[
            CriterionResult(item.id, Rating(ratings.get(item.id, "achieved")), "e")
            for item in scenario.criteria
        ],
        critical_errors=[
            CriticalErrorResult(error, errors, "e")
            for error in scenario.critical_errors
        ],
    )


@pytest.mark.parametrize(
    ("ratings", "critical", "usable"),
    [
        ({}, False, True),
        (
            {"trustworthy": "partly_achieved", "moves-forward": "partly_achieved"},
            False,
            True,
        ),
        ({"trustworthy": "not_achieved"}, False, False),
        ({"moves-forward": "not_achieved"}, False, False),
        (
            {"encouraging": "not_achieved", "easy-to-follow": "not_achieved"},
            False,
            True,
        ),
        ({}, True, False),
    ],
)
def test_usable_answer_floor(ratings, critical, usable):
    evaluation = _evaluation(_scenario(), ratings=ratings, errors=critical)

    assert evaluation.usable is usable


def test_usable_is_not_defined_outside_chat():
    assert _evaluation(_tutor_suggestion()).usable is None


def test_summary_reports_usable_share_usage_weighting_and_criteria():
    programming = _scenario(id="rubric-programming", mode="PROGRAMMING_EXERCISE_CHAT")
    course = _scenario(id="rubric-course")
    evaluations = [
        _evaluation(programming),
        _evaluation(course, ratings={"trustworthy": "not_achieved"}),
    ]

    model = summarize(evaluations)["models"]["m"]

    assert model["usableShare"] == pytest.approx(0.5)
    # programming scores 100, course 80 (four achieved, one not achieved)
    weights = CHAT_MODE_USAGE_WEIGHTS
    expected = (
        weights["PROGRAMMING_EXERCISE_CHAT"] * 100 + weights["COURSE_CHAT"] * 80
    ) / (weights["PROGRAMMING_EXERCISE_CHAT"] + weights["COURSE_CHAT"])
    assert model["usageWeightedScore"] == pytest.approx(expected, abs=0.01)
    assert model["criterionScores"]["trustworthy"] == pytest.approx(50.0)
    assert model["criterionScores"]["encouraging"] == pytest.approx(100.0)


def _rate_card():
    return SimpleNamespace(
        candidates=(
            ModelRate("gpt-5.4-mini", Decimal("0.75"), Decimal("4.5")),
            ModelRate("gpt-6-luna-medium", Decimal("0"), Decimal("0")),
            ModelRate("openai/gpt-oss-120b", Decimal("0"), Decimal("0")),
            ModelRate("gpt-6.1-sol", Decimal("0"), Decimal("0")),
            ModelRate("gpt-6-luna", Decimal("0"), Decimal("0")),
            ModelRate("gpt-6.1-sol-medium", Decimal("0"), Decimal("0")),
            ModelRate("gpt-6-luna-high", Decimal("0"), Decimal("0")),
            ModelRate("gpt-5.5", Decimal("5"), Decimal("30")),
            ModelRate("gpt-5.6-sol", Decimal("5"), Decimal("30")),
            ModelRate("gpt-5.6-terra", Decimal("2.5"), Decimal("15")),
            ModelRate("gpt-5.6-luna", Decimal("1"), Decimal("6")),
        ),
        judge=ModelRate("gpt-5.4", Decimal("2.5"), Decimal("15")),
        auxiliary=ModelRate("gpt-5.4-mini", Decimal("0.75"), Decimal("4.5")),
        confirmed=False,
        source="test rates",
    )


def test_skipping_the_judge_removes_its_cost_from_reserve_and_plan():
    scenario = _scenario()
    card = _rate_card()

    with_judge = trial_reserve(scenario, card, "gpt-6-luna-medium")
    without_judge = trial_reserve(
        scenario, card, "gpt-6-luna-medium", include_judge=False
    )
    plan = build_cost_plan(
        [scenario],
        card,
        repetitions=1,
        ledger=SimpleNamespace(total=lambda: Decimal(0)),
        hard_limit=Decimal(30),
        models=("gpt-6-luna-medium",),
        include_judge=False,
    )

    assert without_judge < with_judge
    assert plan.judge_cost == 0
    assert plan.subtotal == without_judge


def _logos_only_config(tmp_path):
    path = tmp_path / "llm-config.yml"
    path.write_text(
        yaml.safe_dump(
            [
                {
                    "type": "openai_chat",
                    "model": "gpt-6-luna",
                    "base_url": "https://logos.aet.cit.tum.de/v1",
                    "api_key": "logos-test-key",  # pragma: allowlist secret
                }
            ]
        ),
        encoding="utf-8",
    )
    return path


@pytest.mark.usefixtures("isolated_environment")
def test_logos_only_configuration_needs_the_judge_to_be_skipped(tmp_path):
    with pytest.raises(ValueError, match="exactly one credential-bearing"):
        apply_local_llm_config(_logos_only_config(tmp_path))


@pytest.mark.usefixtures("isolated_environment")
def test_logos_only_configuration_serves_candidate_and_helper_from_logos(tmp_path):
    apply_local_llm_config(_logos_only_config(tmp_path), judge=False)

    configuration = create_worker_configuration(
        _rate_card(), "gpt-6-luna-medium", skip_judge=True
    )
    try:
        models = yaml.safe_load(
            Path(configuration.environment["LLM_CONFIG_PATH"]).read_text(
                encoding="utf-8"
            )
        )
    finally:
        configuration.close()

    by_id = {model["id"]: model for model in models}
    assert set(by_id) == {"qa-gpt-6-luna-medium", "qa-aux-mini"}
    assert all(model["type"] == "openai_chat" for model in models)
    assert by_id["qa-gpt-6-luna-medium"]["reasoning_effort"] == "medium"
    assert by_id["qa-aux-mini"]["model"] == "gpt-5.4-mini"
    assert by_id["qa-aux-mini"]["use_responses_api"] is False
    with pytest.raises(ValueError, match="judge to be skipped"):
        create_worker_configuration(_rate_card(), "gpt-6-luna-medium")
    with pytest.raises(ValueError, match="only run Logos candidates"):
        create_worker_configuration(_rate_card(), "gpt-5.5", skip_judge=True)


@pytest.mark.usefixtures("isolated_environment")
def test_azure_helper_without_judge_deployment(monkeypatch):
    monkeypatch.delenv("IRIS_QA_JUDGE_DEPLOYMENT", raising=False)
    monkeypatch.setenv("IRIS_QA_AZURE_ENDPOINT", "https://qa.openai.azure.com")
    monkeypatch.setenv("IRIS_QA_GPT_54_MINI_DEPLOYMENT", "mini")
    monkeypatch.setenv("IRIS_QA_LOGOS_BASE_URL", "https://logos.aet.cit.tum.de/v1")
    monkeypatch.setenv(
        "IRIS_QA_LOGOS_API_KEY", "logos-test-key"
    )  # pragma: allowlist secret
    monkeypatch.setenv("IRIS_QA_GPT_6_LUNA_MODEL", "gpt-6-luna")

    configuration = create_worker_configuration(
        _rate_card(), "gpt-6-luna-medium", skip_judge=True
    )
    try:
        models = yaml.safe_load(
            Path(configuration.environment["LLM_CONFIG_PATH"]).read_text(
                encoding="utf-8"
            )
        )
    finally:
        configuration.close()

    assert {model["id"] for model in models} == {
        "qa-gpt-54-mini",
        "qa-gpt-6-luna-medium",
        "qa-aux-mini",
    }


def _collect(run_root: Path, scenarios: list[Scenario], model="gpt-6-luna-medium"):
    """Write what ``run --skip-judge`` leaves behind, with one failed trial."""
    raw = run_root / "raw"
    raw.mkdir(parents=True)
    trials = []
    for index, scenario in enumerate(scenarios):
        stem = f"{model}-{scenario.id}-r1"
        failed = index == len(scenarios) - 1
        payload = {
            "scenarioId": scenario.id,
            "model": model,
            "response": None if failed else f"answer {index}",
            "activities": [],
            "diagnostics": {},
            "usage": [],
            "executionError": "Boom" if failed else None,
        }
        if not failed:
            payload["judgePending"] = True
            payload["judgeInput"] = {
                "systemPrompt": JUDGE_SYSTEM_PROMPT,
                "request": build_judge_request(scenario, payload["response"], [], {}),
            }
        (raw / f"{stem}.output.json").write_text(
            json.dumps(payload, default=str), encoding="utf-8"
        )
        trials.append(
            {
                "model": model,
                "scenarioId": scenario.id,
                "repetition": 1,
                "stem": stem,
                "durationSeconds": 1.5,
                "executionError": payload["executionError"],
                "judgePending": not failed,
            }
        )
    (run_root / COLLECTION_FILE).write_text(
        json.dumps({"metadata": {"models": [model]}, "trials": trials}),
        encoding="utf-8",
    )


def test_export_blinds_the_bundles_and_import_scores_the_judgments(tmp_path):
    scenarios = _real_chat(3)
    by_id = {scenario.id: scenario for scenario in scenarios}
    run_root = tmp_path / "run"
    _collect(run_root, scenarios)
    exported = tmp_path / "judge"

    count = export_judge_bundles(run_root=run_root, output_root=exported)

    assert count == 2
    bundles = sorted((exported / "bundles").glob("*.json"))
    assert [bundle.stem for bundle in bundles] == ["t001", "t002"]
    for bundle in bundles:
        text = bundle.read_text(encoding="utf-8")
        assert "luna" not in text and "gpt-6" not in text
        content = json.loads(text)
        assert content["systemPrompt"] == JUDGE_SYSTEM_PROMPT
        assert content["request"]["referenceFacts"]
    key = json.loads((exported / KEY_FILE).read_text(encoding="utf-8"))
    judgments = tmp_path / "judgments"
    judgments.mkdir()
    for bundle_id, trial in key["trials"].items():
        (judgments / f"{bundle_id}.json").write_text(
            json.dumps(_judgment(by_id[trial["scenarioId"]])), encoding="utf-8"
        )

    code, evaluations = import_judgments(
        run_root=run_root,
        judgments_root=judgments,
        key_path=exported / KEY_FILE,
        output_root=tmp_path / "report",
        scenarios=by_id,
        judge_label="external-test-judge",
    )

    assert code == 1  # the failed trial is an execution error
    assert sorted(item.score for item in evaluations) == [0.0, 100.0, 100.0]
    report = json.loads(
        (tmp_path / "report" / "report.json").read_text(encoding="utf-8")
    )
    assert report["metadata"]["judge"] == "external-test-judge"
    assert (tmp_path / "report" / "report.md").exists()


def test_import_names_missing_and_invalid_judgments(tmp_path):
    scenarios = _real_chat(3)
    by_id = {scenario.id: scenario for scenario in scenarios}
    run_root = tmp_path / "run"
    _collect(run_root, scenarios)
    exported = tmp_path / "judge"
    export_judge_bundles(run_root=run_root, output_root=exported)
    key = json.loads((exported / KEY_FILE).read_text(encoding="utf-8"))
    judgments = tmp_path / "judgments"
    judgments.mkdir()
    first, second = sorted(key["trials"])
    invalid = _judgment(by_id[key["trials"][first]["scenarioId"]])
    invalid["criteria"][0]["rating"] = "great"
    (judgments / f"{first}.json").write_text(json.dumps(invalid), encoding="utf-8")

    with pytest.raises(ValueError) as error:
        import_judgments(
            run_root=run_root,
            judgments_root=judgments,
            key_path=exported / KEY_FILE,
            output_root=tmp_path / "report",
            scenarios=by_id,
            judge_label="external-test-judge",
        )

    message = str(error.value)
    assert f"{first}: invalid judge rating" in message
    assert f"{second}: no judgment file" in message


def test_evaluation_from_worker_still_needs_a_judge_unless_the_trial_failed():
    scenario = _scenario()

    with pytest.raises(ValueError, match="missing the judge result"):
        evaluation_from_worker(
            scenario,
            model="m",
            repetition=1,
            payload={"response": "x", "usage": []},
            duration_seconds=0,
        )
    evaluation = evaluation_from_worker(
        scenario,
        model="m",
        repetition=1,
        payload={"response": None, "usage": [], "executionError": "Boom"},
        duration_seconds=0,
    )
    assert evaluation.score == 0.0
    assert shared_criteria()[0]["id"] == "trustworthy"


def test_skipping_the_judge_collects_answers_and_reserves_only_the_pipeline(
    tmp_path, monkeypatch
):
    scenario = _real_chat(1)[0]
    card = _rate_card()
    ledger = SpendLedger(tmp_path / "spend.jsonl")
    configuration_calls = []
    worker_commands = []
    pipeline_reserve = trial_reserve(
        scenario, card, "gpt-6-luna-medium", include_judge=False
    )

    def configuration(*_args, **kwargs):
        configuration_calls.append(kwargs)
        return SimpleNamespace(environment={}, close=lambda: None)

    def worker(args, **_kwargs):
        worker_commands.append(args)
        assert ledger.total() == pipeline_reserve
        Path(args[args.index("--output") + 1]).write_text(
            json.dumps(
                {
                    "scenarioId": scenario.id,
                    "model": "gpt-6-luna-medium",
                    "response": "An answer.",
                    "activities": [],
                    "usage": [
                        {
                            "model": "gpt-5.4-mini",
                            "pipeline": "chat",
                            "inputTokens": 100,
                            "outputTokens": 50,
                            "costUsd": 0.0003,
                        }
                    ],
                    "judgePending": True,
                    "judgeInput": {"systemPrompt": "p", "request": {}},
                    "executionError": None,
                }
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr("iris.qa.run.create_worker_configuration", configuration)
    monkeypatch.setattr("iris.qa.run.subprocess.run", worker)
    monkeypatch.setattr("iris.qa.run._git_value", lambda *_args: "test")

    code, root, evaluations = run_paid_suite(
        qa_root=tmp_path / "qa",
        scenarios=[scenario],
        models=("gpt-6-luna-medium",),
        repetitions=1,
        rate_card=card,
        ledger=ledger,
        hard_limit=Decimal("30"),
        max_run_cost=Decimal("30"),
        planned_cost=pipeline_reserve,
        output_root=tmp_path / "collected",
        skip_judge=True,
    )

    assert code == 0
    assert not evaluations
    assert configuration_calls == [{"skip_judge": True}]
    assert "--skip-judge" in worker_commands[0]
    collection = json.loads((root / COLLECTION_FILE).read_text(encoding="utf-8"))
    assert collection["metadata"]["judge"] == "external"
    assert [trial["scenarioId"] for trial in collection["trials"]] == [scenario.id]
    assert collection["trials"][0]["judgePending"] is True
    assert not (root / "report.md").exists()
    records = ledger.records()
    assert len(records) == 1
    assert records[0].reservation is False
