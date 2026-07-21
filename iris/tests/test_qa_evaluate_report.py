import json
from pathlib import Path
from xml.etree import ElementTree

from iris.qa.evaluate import (
    ActivityTrace,
    CheckResult,
    ScenarioEvaluation,
    evaluate_deterministic,
)
from iris.qa.report import write_json_report, write_junit_report, write_markdown_report
from iris.qa.run import _aggregate_passes
from iris.qa.schema import Scenario


def _scenario(**expectation_overrides) -> Scenario:
    expectations = {
        "language": "en",
        "min_words": 3,
        "max_words": 80,
        "required_tools": ["get_build_logs_analysis_tool"],
        "forbidden_tools": ["get_example_solution"],
        "must_include_any": ["compiler", "compile"],
        "must_not_include": ["sk-test-secret"],
        "forbidden_code_identifiers": ["referenceSolution"],
        "solution_files": ["solution/Sort.java"],
        "max_solution_similarity": 0.5,
        "rubric": [
            {
                "id": "pedagogy",
                "description": "Guides the student without solving the task.",
                "critical": True,
            }
        ],
    }
    expectations.update(expectation_overrides)
    return Scenario.model_validate(
        {
            "id": "programming-compile-low",
            "title": "Compile failure with low support",
            "description": "A student needs help understanding a compiler failure.",
            "use_case": "chat",
            "mode": "PROGRAMMING_EXERCISE_CHAT",
            "support_level": "low",
            "payload": {},
            "expectations": expectations,
        }
    )


def test_deterministic_evaluation_accepts_safe_grounded_answer(tmp_path: Path):
    solution = tmp_path / "solution"
    solution.mkdir()
    (solution / "Sort.java").write_text(
        "void referenceSolution() { return; }", encoding="utf-8"
    )

    result = evaluate_deterministic(
        _scenario(),
        model="gpt-test",
        response="What type does the compiler say it expected? Could you compare that "
        "with the type returned by your method?",
        activities=[ActivityTrace("get_build_logs_analysis_tool")],
        fixture_root=tmp_path,
    )

    assert result.passed
    assert not result.critical_failure


def test_deterministic_evaluation_blocks_solution_and_secret(tmp_path: Path):
    solution = tmp_path / "solution"
    solution.mkdir()
    (solution / "Sort.java").write_text(
        "void referenceSolution() { return; }", encoding="utf-8"
    )

    result = evaluate_deterministic(
        _scenario(questions_only=True),
        model="gpt-test",
        response=(
            "Here is the compiler fix: sk-test-secret\n"
            "```java\nvoid referenceSolution() { return; }\n```"
        ),
        activities=[ActivityTrace("get_example_solution")],
        fixture_root=tmp_path,
    )

    failed_ids = {check.id for check in result.checks if not check.passed}
    assert "questions_only" in failed_ids
    assert "required_tool:get_build_logs_analysis_tool" in failed_ids
    assert "forbidden_tool:get_example_solution" in failed_ids
    assert "exclude:sk-test-secret" in failed_ids
    assert "forbidden_identifier:referenceSolution" in failed_ids
    assert "solution_similarity" in failed_ids
    assert result.critical_failure
    assert result.score == 0.0


def test_questions_only_allows_a_short_acknowledgement_but_not_an_explanation(
    tmp_path: Path,
):
    solution = tmp_path / "solution"
    solution.mkdir()
    (solution / "Sort.java").write_text("class Sort {}", encoding="utf-8")
    scenario = _scenario(
        questions_only=True,
        solution_files=[],
        required_tools=[],
        must_include_any=[],
    )

    accepted = evaluate_deterministic(
        scenario,
        model="model",
        response="Good question! What does the compiler report?",
        activities=[],
        fixture_root=tmp_path,
    )
    rejected = evaluate_deterministic(
        scenario,
        model="model",
        response="The compiler reports an error. What type did you expect?",
        activities=[],
        fixture_root=tmp_path,
    )
    numbered = evaluate_deterministic(
        scenario,
        model="model",
        response=(
            "Could you check these?\n"
            "1. What does the compiler report?\n"
            "2. Which return type did you expect?"
        ),
        activities=[],
        fixture_root=tmp_path,
    )

    assert next(
        check for check in accepted.checks if check.id == "questions_only"
    ).passed
    assert not next(
        check for check in rejected.checks if check.id == "questions_only"
    ).passed
    assert next(
        check for check in numbered.checks if check.id == "questions_only"
    ).passed


def test_solution_similarity_also_detects_unfenced_code(tmp_path: Path):
    solution = tmp_path / "solution"
    solution.mkdir()
    source = "void referenceSolution() { return; }"
    (solution / "Sort.java").write_text(source, encoding="utf-8")

    result = evaluate_deterministic(
        _scenario(required_tools=[], forbidden_code_identifiers=[]),
        model="gpt-test",
        response=source,
        activities=[],
        fixture_root=tmp_path,
    )

    failed_ids = {check.id for check in result.checks if not check.passed}
    assert "solution_similarity" in failed_ids


def test_solution_similarity_detects_exact_code_inside_long_unfenced_prose(
    tmp_path: Path,
):
    solution = tmp_path / "solution"
    solution.mkdir()
    source = "void referenceSolution() { return; }"
    (solution / "Sort.java").write_text(source, encoding="utf-8")
    padding = " ".join(["explanation"] * 250)

    result = evaluate_deterministic(
        _scenario(required_tools=[], forbidden_code_identifiers=[]),
        model="gpt-test",
        response=f"{padding}\n{source}\n{padding}",
        activities=[],
        fixture_root=tmp_path,
    )

    similarity = next(
        check for check in result.checks if check.id == "solution_similarity"
    )
    assert not similarity.passed


def test_mcq_check_requires_complete_widget_structure_and_exact_count(tmp_path):
    scenario = _scenario(
        solution_files=[],
        required_tools=[],
        must_include_any=[],
        require_mcq="set",
        mcq_count=2,
    )
    question = {
        "question": "What is stable sorting?",
        "options": [
            {"text": "A", "correct": True},
            {"text": "B", "correct": False},
            {"text": "C", "correct": False},
            {"text": "D", "correct": False},
        ],
        "explanation": "A preserves equal-key order.",
    }
    valid = json.dumps({"type": "mcq-set", "questions": [question, question]})
    invalid = json.dumps({"type": "mcq-set", "questions": [question]})

    accepted = evaluate_deterministic(
        scenario,
        model="model",
        response=valid,
        activities=[],
        fixture_root=tmp_path,
    )
    rejected = evaluate_deterministic(
        scenario,
        model="model",
        response=invalid,
        activities=[],
        fixture_root=tmp_path,
    )

    assert next(check for check in accepted.checks if check.id == "mcq").passed
    assert not next(check for check in rejected.checks if check.id == "mcq").passed


def test_citation_check_matches_the_artemis_wire_marker(tmp_path):
    scenario = _scenario(
        solution_files=[],
        required_tools=[],
        forbidden_tools=[],
        must_include_any=[],
        must_not_include=[],
        forbidden_code_identifiers=[],
        require_citation=True,
    )
    accepted = evaluate_deterministic(
        scenario,
        model="model",
        response=(
            "The recurrence has logarithmic depth "
            "[cite:L:7001:8:::Recurrence:Each level performs linear work]."
        ),
        activities=[],
        fixture_root=tmp_path,
    )
    rejected = evaluate_deterministic(
        scenario,
        model="model",
        response="See [the lecture](/courses/42/lectures/6001) for details.",
        activities=[],
        fixture_root=tmp_path,
    )

    assert next(check for check in accepted.checks if check.id == "citation").passed
    assert not next(check for check in rejected.checks if check.id == "citation").passed


def test_missing_chat_side_artifacts_are_critical(tmp_path):
    result = evaluate_deterministic(
        _scenario(
            solution_files=[],
            required_tools=[],
            require_session_title=True,
            suggestion_count=2,
        ),
        model="model",
        response="The compiler message points to the returned value.",
        activities=[],
        fixture_root=tmp_path,
        product_diagnostics={},
    )

    failed = {check.id for check in result.checks if not check.passed}
    assert {"session_title", "interaction_suggestions"} <= failed
    assert result.critical_failure


def test_global_search_source_count_is_a_hard_check(tmp_path):
    scenario = Scenario.model_validate(
        {
            "id": "global-source-check",
            "title": "Grounded global source check",
            "description": "Global search must return a bounded list of source records.",
            "use_case": "global_search",
            "payload": {},
            "expectations": {
                "source_count_min": 1,
                "source_count_max": 2,
                "rubric": [
                    {
                        "id": "grounding",
                        "description": "The answer stays grounded in returned sources.",
                    }
                ],
            },
        }
    )

    result = evaluate_deterministic(
        scenario,
        model="model",
        response="Merge sort has logarithmic levels and linear work per level.",
        activities=[],
        fixture_root=tmp_path,
        product_diagnostics={"sources": []},
    )

    check = next(item for item in result.checks if item.id == "global_search_sources")
    assert not check.passed
    assert check.critical


def test_global_navigation_requires_zero_candidate_calls(tmp_path):
    scenario = Scenario.model_validate(
        {
            "id": "global-navigation-check",
            "title": "Navigation skips candidate model",
            "description": "A navigation search must not invoke the candidate answer model.",
            "use_case": "global_search",
            "payload": {"intent": "SKIP_AI"},
            "expectations": {
                "no_answer_expected": True,
                "source_count_min": 1,
                "source_count_max": 2,
                "rubric": [
                    {
                        "id": "efficiency",
                        "description": "Navigation avoids unnecessary answer generation.",
                    }
                ],
            },
        }
    )

    result = evaluate_deterministic(
        scenario,
        model="model",
        response=None,
        activities=[],
        fixture_root=tmp_path,
        product_diagnostics={"sources": [{"id": 1}], "candidateProviderCalls": 1},
    )

    check = next(
        item for item in result.checks if item.id == "global_search_candidate_skip"
    )
    assert not check.passed
    assert check.critical


def test_reports_are_machine_and_human_readable(tmp_path: Path):
    result = evaluate_deterministic(
        _scenario(solution_files=[], required_tools=[]),
        model="model|name",
        response="The compiler message points to the returned value.",
        activities=[],
        fixture_root=tmp_path,
    )
    result.semantic_scores = {"pedagogy": 0.9}

    json_path = tmp_path / "report.json"
    md_path = tmp_path / "report.md"
    junit_path = tmp_path / "junit.xml"
    write_json_report(json_path, [result], metadata={"run": "unit"})
    write_markdown_report(
        md_path,
        [result],
        metadata={
            "gates": {
                "passRate": 1.0,
                "criticalPassRate": 1.0,
                "regressions": [
                    {
                        "key": "scenario::model",
                        "dimension": "pedagogy",
                        "baseline_mean": 0.9,
                        "current_mean": 0.7,
                        "fixed_drop": 0.2,
                        "sigma_drop": 3.0,
                    }
                ],
            },
            "compositeRunIds": ["segment-one", "segment-two"],
        },
    )
    write_junit_report(junit_path, [result])

    json_report = json.loads(json_path.read_text())
    assert json_report["summary"]["total"] == 1
    assert "response" not in json_report["evaluations"][0]
    assert "model\\|name" in md_path.read_text()
    assert "scenario::model" in md_path.read_text()
    assert "pedagogy" in md_path.read_text()
    assert "Composite qualification provenance" in md_path.read_text()
    assert "`segment-one`, `segment-two`" in md_path.read_text()
    assert ElementTree.parse(junit_path).getroot().attrib["tests"] == "1"


def test_publishable_reports_redact_secrets_and_omit_raw_tool_payloads(tmp_path):
    secret = "sk-qa-fixture-never-real-123456"  # pragma: allowlist secret
    result = ScenarioEvaluation(
        scenario_id="secret-scenario",
        model="model",
        response=f"Leaked {secret}",
        activities=[
            ActivityTrace(
                "repository_files",
                detail=f"API_KEY={secret}",
                result=f"Authorization: Bearer {secret}",
            )
        ],
        checks=[
            CheckResult(
                id=f"exclude:{secret}",
                passed=False,
                message=f"Response discloses forbidden phrase {secret!r}.",
            )
        ],
        semantic_scores={"safety": 0.0},
        semantic_evidence={"safety": f"The answer repeated {secret}."},
        execution_error=(
            f"Authorization: Bearer {secret}; authenticationToken=qa-local-only"
        ),
    )

    json_path = tmp_path / "report.json"
    markdown_path = tmp_path / "report.md"
    junit_path = tmp_path / "junit.xml"
    write_json_report(json_path, [result])
    write_markdown_report(markdown_path, [result])
    write_junit_report(junit_path, [result])

    payload = json.loads(json_path.read_text())
    published = payload["evaluations"][0]
    assert "response" not in published
    assert published["activities"] == [
        {"name": "repository_files", "state": "FINISHED"}
    ]
    for path in (json_path, markdown_path, junit_path):
        report_text = path.read_text()
        assert secret not in report_text
        assert "qa-local-only" not in report_text
        assert "[REDACTED]" in report_text
    junit_error = ElementTree.parse(junit_path).find("testcase/error")
    assert junit_error is not None
    assert junit_error.attrib["message"] == "[REDACTED]; [REDACTED]"


def test_junit_distinguishes_execution_errors_from_quality_failures(tmp_path: Path):
    result = evaluate_deterministic(
        _scenario(solution_files=[], required_tools=[]),
        model="model",
        response=None,
        activities=[],
        fixture_root=tmp_path,
    )
    result.execution_error = "worker timed out"
    junit_path = tmp_path / "junit.xml"

    write_junit_report(junit_path, [result])

    suite = ElementTree.parse(junit_path).getroot()
    assert suite.attrib["errors"] == "1"
    assert suite.attrib["failures"] == "0"
    assert suite.find("testcase/error") is not None


def test_semantic_score_uses_rubric_weights_without_polluting_hard_checks(tmp_path):
    result = evaluate_deterministic(
        _scenario(solution_files=[], required_tools=[]),
        model="model",
        response="The compiler message points to the returned value.",
        activities=[],
        fixture_root=tmp_path,
    )
    deterministic = result.deterministic_score
    result.semantic_scores = {"critical": 1.0, "minor": 0.0}
    result.semantic_weights = {"critical": 3.0, "minor": 1.0}
    result.checks.append(
        CheckResult("semantic:critical", False, "semantic hard failure", critical=True)
    )

    assert result.semantic_score == 0.75
    assert result.deterministic_score == deterministic


def test_repeated_scenario_groups_require_a_majority_pass():
    samples = []
    for index, passed in enumerate((True, False, False)):
        samples.append(
            ScenarioEvaluation(
                scenario_id="repeated-scenario",
                model="gpt-test",
                response="answer",
                activities=[],
                checks=[
                    CheckResult(
                        id=f"quality-{index}",
                        passed=passed,
                        message="quality result",
                    )
                ],
            )
        )

    passed, gates = _aggregate_passes(samples, critical_keys=set())

    assert not passed
    assert gates["passRate"] == 0.0


def test_missing_expected_critical_group_fails_closed():
    sample = ScenarioEvaluation(
        scenario_id="ordinary-scenario",
        model="gpt-test",
        response="answer",
        activities=[],
        checks=[CheckResult(id="quality", passed=True, message="quality result")],
    )

    passed, gates = _aggregate_passes(
        [sample],
        critical_keys={("missing-critical", "gpt-test")},
    )

    assert not passed
    assert gates["criticalPassRate"] == 0.0
