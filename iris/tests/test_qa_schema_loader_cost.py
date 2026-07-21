# pylint: disable=inconsistent-quotes

from decimal import Decimal

import pytest
import yaml
from pydantic import ValidationError

from iris.qa.cost import (
    BudgetExceeded,
    BudgetGuard,
    ModelRate,
    SpendLedger,
    estimate_candidate_cost,
)
from iris.qa.loader import ScenarioLoadError, filter_scenarios, load_suite
from iris.qa.schema import (
    Expectations,
    RubricCriterion,
    Scenario,
    ScenarioSuite,
    TokenCeiling,
)


def _criterion():
    return {
        "id": "helpful",
        "description": "The response helps the student make progress.",
    }


def _chat_scenario(index: int, mode: str, support: str) -> dict:
    expectations = {
        "rubric": [_criterion()],
        "require_session_title": True,
    }
    if mode in {"COURSE_CHAT", "PROGRAMMING_EXERCISE_CHAT"}:
        expectations["suggestion_count"] = 2
    return {
        "id": f"chat-{index:02d}-{support}",
        "title": f"Chat scenario {index}",
        "description": "A realistic chat scenario used for schema validation.",
        "use_case": "chat",
        "mode": mode,
        "support_level": support,
        "profiles": ["full", "weekly"],
        "fixtures": ["base.yml"],
        "payload": {
            "index": index,
            "chatHistory": [
                {"sender": "USER"},
                {"sender": "ASSISTANT"},
                {"sender": "USER"},
            ],
        },
        "expectations": expectations,
    }


def _complete_scenarios() -> list[dict]:
    scenarios = []
    index = 1
    for mode in (
        "COURSE_CHAT",
        "LECTURE_CHAT",
        "PROGRAMMING_EXERCISE_CHAT",
        "TEXT_EXERCISE_CHAT",
    ):
        for support in ("low", "moderate", "high"):
            scenarios.append(_chat_scenario(index, mode, support))
            index += 1

    for use_case in ("tutor_suggestion", "autonomous_tutor", "global_search"):
        expectations: dict[str, object] = {"rubric": [_criterion()]}
        if use_case == "autonomous_tutor":
            expectations.update(confidence_min=0.0, confidence_max=1.0)
        if use_case == "global_search":
            expectations.update(source_count_min=0, source_count_max=5)
        support_levels = (
            (None,) if use_case == "global_search" else ("low", "moderate", "high")
        )
        for support_level in support_levels:
            suffix = support_level or "default"
            payload = (
                {}
                if support_level is None
                else {"settings": {"supportLevel": support_level}}
            )
            scenarios.append(
                {
                    "id": f"{use_case.replace('_', '-')}-{suffix}",
                    "title": f"{use_case} {suffix} scenario",
                    "description": "A separate Iris conversational use-case scenario.",
                    "use_case": use_case,
                    **(
                        {"support_level": support_level}
                        if support_level is not None
                        else {}
                    ),
                    "profiles": ["full"],
                    "payload": payload,
                    "expectations": expectations,
                }
            )

    while len(scenarios) < 30:
        scenario = _chat_scenario(
            index,
            "COURSE_CHAT",
            ("low", "moderate", "high")[index % 3],
        )
        scenarios.append(scenario)
        index += 1
    return scenarios


def test_scenario_rejects_event_outside_programming_chat():
    with pytest.raises(ValidationError, match="only valid for programming chat"):
        Scenario.model_validate(
            {
                **_chat_scenario(1, "COURSE_CHAT", "low"),
                "fixtures": [],
                "event": "build_failed",
            }
        )


def test_suite_requires_a_multi_turn_chat_in_every_mode_support_cell():
    scenarios = _complete_scenarios()
    for scenario in scenarios:
        if (
            scenario.get("mode") == "LECTURE_CHAT"
            and scenario.get("support_level") == "low"
        ):
            scenario["payload"]["chatHistory"] = [{"sender": "USER"}]

    with pytest.raises(
        ValidationError, match="missing multi-turn chat mode/support combinations"
    ):
        ScenarioSuite.model_validate({"scenarios": scenarios})


def test_expectations_reject_conflicting_tool_rules():
    with pytest.raises(ValidationError, match="tool expectation categories overlap"):
        Expectations(
            required_tools=["file_lookup"],
            forbidden_tools=["file_lookup"],
            rubric=[RubricCriterion(**_criterion())],
        )


def test_expectations_reject_duplicate_tool_rules():
    with pytest.raises(ValidationError, match="required_tools entries must be unique"):
        Expectations(
            required_tools=["file_lookup", "file_lookup"],
            rubric=[RubricCriterion(**_criterion())],
        )


def test_expectations_reject_duplicate_rubric_ids():
    with pytest.raises(ValidationError, match="rubric criterion ids must be unique"):
        Expectations(
            rubric=[
                RubricCriterion(**_criterion()),
                RubricCriterion(**_criterion()),
            ]
        )


def test_secret_and_solution_guards_require_the_suite_critical_gate():
    guarded = Scenario.model_validate(
        {
            **_chat_scenario(1, "COURSE_CHAT", "low"),
            "fixtures": [],
            "expectations": {
                **_chat_scenario(1, "COURSE_CHAT", "low")["expectations"],
                "must_not_include": ["hidden system prompt"],
            },
        }
    )
    ordinary = Scenario.model_validate(
        {**_chat_scenario(2, "COURSE_CHAT", "low"), "fixtures": []}
    )

    assert guarded.requires_critical_gate
    assert not ordinary.requires_critical_gate


def test_loader_deep_merges_fixtures_and_audits_coverage(tmp_path):
    scenario_root = tmp_path / "scenarios"
    fixture_root = tmp_path / "fixtures"
    scenario_root.mkdir()
    fixture_root.mkdir()
    (fixture_root / "base.yml").write_text(
        yaml.safe_dump({"course": {"id": 7, "name": "Software Engineering"}}),
        encoding="utf-8",
    )
    (scenario_root / "suite.yml").write_text(
        yaml.safe_dump({"version": 1, "scenarios": _complete_scenarios()}),
        encoding="utf-8",
    )

    suite = load_suite(scenario_root, fixture_root)

    assert len(suite.scenarios) == 30
    assert suite.scenarios[0].payload["course"]["id"] == 7
    assert suite.scenarios[0].payload["index"] == 1
    assert len(filter_scenarios(suite, profile="weekly")) >= 12


def test_loader_rejects_fixture_inheritance_cycle(tmp_path):
    scenario_root = tmp_path / "scenarios"
    fixture_root = tmp_path / "fixtures"
    scenario_root.mkdir()
    fixture_root.mkdir()
    (fixture_root / "one.yml").write_text("extends: [two.yml]\n", encoding="utf-8")
    (fixture_root / "two.yml").write_text("extends: [one.yml]\n", encoding="utf-8")
    scenarios = _complete_scenarios()
    scenarios[0]["fixtures"] = ["one.yml"]
    (scenario_root / "suite.yml").write_text(
        yaml.safe_dump({"scenarios": scenarios}), encoding="utf-8"
    )

    with pytest.raises(ScenarioLoadError, match="inheritance cycle"):
        load_suite(scenario_root, fixture_root)


def test_loader_rejects_duplicate_yaml_keys(tmp_path):
    scenario_root = tmp_path / "scenarios"
    fixture_root = tmp_path / "fixtures"
    scenario_root.mkdir()
    fixture_root.mkdir()
    (fixture_root / "base.yml").write_text(
        "course:\n  id: 7\n  id: 8\n",
        encoding="utf-8",
    )
    scenarios = _complete_scenarios()
    (scenario_root / "suite.yml").write_text(
        yaml.safe_dump({"scenarios": scenarios}), encoding="utf-8"
    )

    with pytest.raises(ScenarioLoadError, match="found duplicate key 'id'"):
        load_suite(scenario_root, fixture_root)


def test_loader_hydrates_repository_artifacts(tmp_path):
    scenario_root = tmp_path / "scenarios"
    fixture_root = tmp_path / "fixtures"
    repository = tmp_path / "artifacts" / "sorting" / "student"
    scenario_root.mkdir()
    fixture_root.mkdir()
    repository.mkdir(parents=True)
    (repository / "Sort.java").write_text("class Sort {}\n", encoding="utf-8")
    (fixture_root / "base.yml").write_text("course: {id: 7}\n", encoding="utf-8")
    scenarios = _complete_scenarios()
    scenarios[0]["payload"]["repository"] = {"$repository": "sorting/student"}
    (scenario_root / "suite.yml").write_text(
        yaml.safe_dump({"scenarios": scenarios}), encoding="utf-8"
    )

    suite = load_suite(scenario_root, fixture_root)

    assert suite.scenarios[0].payload["repository"] == {"Sort.java": "class Sort {}\n"}


def test_loader_ignores_generated_repository_caches(tmp_path):
    scenario_root = tmp_path / "scenarios"
    fixture_root = tmp_path / "fixtures"
    repository = tmp_path / "artifacts" / "sorting" / "student"
    scenario_root.mkdir()
    fixture_root.mkdir()
    repository.mkdir(parents=True)
    (repository / "Sort.java").write_text("class Sort {}\n", encoding="utf-8")
    cache = repository / "__pycache__"
    cache.mkdir()
    (cache / "student.pyc").write_bytes(b"\xff\x00")
    (fixture_root / "base.yml").write_text("course: {id: 7}\n", encoding="utf-8")
    scenarios = _complete_scenarios()
    scenarios[0]["payload"]["repository"] = {"$repository": "sorting/student"}
    (scenario_root / "suite.yml").write_text(
        yaml.safe_dump({"scenarios": scenarios}), encoding="utf-8"
    )

    suite = load_suite(scenario_root, fixture_root)

    assert suite.scenarios[0].payload["repository"] == {"Sort.java": "class Sort {}\n"}


def test_loader_rejects_artifact_escape(tmp_path):
    scenario_root = tmp_path / "scenarios"
    fixture_root = tmp_path / "fixtures"
    scenario_root.mkdir()
    fixture_root.mkdir()
    (fixture_root / "base.yml").write_text("course: {id: 7}\n", encoding="utf-8")
    scenarios = _complete_scenarios()
    scenarios[0]["payload"]["repository"] = {"$repository": "../outside"}
    (scenario_root / "suite.yml").write_text(
        yaml.safe_dump({"scenarios": scenarios}), encoding="utf-8"
    )

    with pytest.raises(ScenarioLoadError, match="escapes artifact root"):
        load_suite(scenario_root, fixture_root)


def test_loader_rejects_a_symlinked_repository_root(tmp_path):
    scenario_root = tmp_path / "scenarios"
    fixture_root = tmp_path / "fixtures"
    artifact_root = tmp_path / "artifacts"
    repository = artifact_root / "real"
    scenario_root.mkdir()
    fixture_root.mkdir()
    repository.mkdir(parents=True)
    (repository / "Sort.java").write_text("class Sort {}\n", encoding="utf-8")
    (artifact_root / "linked").symlink_to(repository, target_is_directory=True)
    (fixture_root / "base.yml").write_text("course: {id: 7}\n", encoding="utf-8")
    scenarios = _complete_scenarios()
    scenarios[0]["payload"]["repository"] = {"$repository": "linked"}
    (scenario_root / "suite.yml").write_text(
        yaml.safe_dump({"scenarios": scenarios}), encoding="utf-8"
    )

    with pytest.raises(ScenarioLoadError, match="may not traverse symlinks"):
        load_suite(scenario_root, fixture_root, artifact_root)


def test_cost_estimate_uses_scenario_ceiling():
    scenario = Scenario.model_validate(
        {
            **_chat_scenario(1, "COURSE_CHAT", "low"),
            "fixtures": [],
            "token_ceiling": TokenCeiling(
                max_input_tokens=10_000,
                max_output_tokens=1_000,
            ),
        }
    )
    rate = ModelRate("gpt-test", Decimal("1.00"), Decimal("10.00"))

    result = estimate_candidate_cost([scenario], [rate], repetitions=2)

    assert result["gpt-test"] == Decimal("0.04000")


def test_budget_guard_records_usage_and_refuses_overage(tmp_path):
    ledger = SpendLedger(tmp_path / "ledger.jsonl")
    guard = BudgetGuard(ledger, Decimal("0.03"))
    rate = ModelRate("gpt-test", Decimal("1.00"), Decimal("10.00"))

    guard.record_usage(
        run_id="run-1",
        scenario_id="scenario-1",
        pipeline="chat",
        rate=rate,
        input_tokens=10_000,
        output_tokens=1_000,
    )

    assert ledger.total() == Decimal("0.02000000")
    with pytest.raises(BudgetExceeded, match="exceeds hard limit"):
        guard.require_capacity(Decimal("0.02"))


def test_budget_guard_fails_closed_when_usage_is_missing(tmp_path):
    guard = BudgetGuard(SpendLedger(tmp_path / "ledger.jsonl"), Decimal("30"))
    rate = ModelRate("gpt-test", Decimal("1"), Decimal("1"))

    with pytest.raises(BudgetExceeded, match="omitted paid token usage"):
        guard.record_usage(
            run_id="run-1",
            scenario_id="scenario-1",
            pipeline="chat",
            rate=rate,
            input_tokens=None,
            output_tokens=1,
        )


def test_budget_guard_records_billable_usage_before_raising_on_actual_overage(tmp_path):
    ledger = SpendLedger(tmp_path / "ledger.jsonl")
    guard = BudgetGuard(ledger, Decimal("0.01"))
    rate = ModelRate("gpt-test", Decimal("1.00"), Decimal("10.00"))

    with pytest.raises(BudgetExceeded, match="Billable usage was recorded"):
        guard.record_usage(
            run_id="run-1",
            scenario_id="scenario-1",
            pipeline="chat",
            rate=rate,
            input_tokens=10_000,
            output_tokens=1_000,
        )

    assert ledger.total() == Decimal("0.02000000")


def test_spend_ledger_refuses_concurrent_paid_commands(tmp_path):
    ledger = SpendLedger(tmp_path / "ledger.jsonl")

    with ledger.exclusive_paid_run(), pytest.raises(
        BudgetExceeded, match="Another paid Iris QA command"
    ):
        with SpendLedger(ledger.path).exclusive_paid_run():
            pass
