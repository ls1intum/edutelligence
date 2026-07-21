from collections import Counter
from pathlib import Path

import pytest

from iris.common.pyris_message import PyrisMessage
from iris.domain.data.image_message_content_dto import ImageMessageContentDTO
from iris.domain.data.json_message_content_dto import JsonMessageContentDTO
from iris.domain.data.text_message_content_dto import TextMessageContentDTO
from iris.qa.contracts import (
    ScenarioContractError,
    validate_scenario_contract,
    validate_suite_contracts,
)
from iris.qa.loader import load_suite
from iris.qa.schema import RiskLevel, UseCase
from iris.tools import (
    create_tool_faq_content_retrieval,
    create_tool_file_lookup,
    create_tool_generate_mcq_questions,
    create_tool_get_build_logs_analysis,
    create_tool_get_competency_list,
    create_tool_get_example_solution,
    create_tool_get_feedbacks,
    create_tool_get_last_artifact,
    create_tool_get_student_exercise_metrics,
    create_tool_get_submission_details,
    create_tool_lecture_content_retrieval,
    create_tool_repository_files,
)

QA_ROOT = Path(__file__).parents[1] / "qa"


def _nested_callable_names(callable_):
    return {
        constant.co_name
        for constant in callable_.__code__.co_consts
        if hasattr(constant, "co_name")
    }


def test_artemis_polymorphic_message_content_round_trips_exact_wire_shape():
    message = PyrisMessage.model_validate(
        {
            "id": 42,
            "sentAt": "2026-05-16T10:00:00Z",
            "sender": "LLM",
            "contents": [
                {"type": "text", "textContent": "Try this."},
                {
                    "type": "json",
                    "jsonContent": {
                        "type": "mcq",
                        "question": "Which is stable?",
                    },
                },
                {"type": "image", "imageData": "YWJj"},
            ],
        }
    )

    assert [type(content) for content in message.contents] == [
        TextMessageContentDTO,
        JsonMessageContentDTO,
        ImageMessageContentDTO,
    ]
    assert [
        content.model_dump(by_alias=True, mode="json", exclude_none=True)
        for content in message.contents
    ] == [
        {"type": "text", "textContent": "Try this."},
        {
            "type": "json",
            "jsonContent": {
                "type": "mcq",
                "question": "Which is stable?",
            },
        },
        {"type": "image", "imageData": "YWJj"},
    ]

    legacy = JsonMessageContentDTO(jsonContent='{"type":"mcq"}')
    assert legacy.json_content == {"type": "mcq"}

    # Artemis omits empty fields via @JsonInclude(NON_EMPTY), so an empty text
    # part can legitimately arrive with only its discriminator.
    empty_text = TextMessageContentDTO.model_validate({"type": "text"})
    assert empty_text.text_content == ""


def test_raw_artemis_json_history_becomes_text_for_model_apis():
    from iris.common.message_converters import (  # pylint: disable=import-outside-toplevel
        convert_iris_message_to_langchain_message,
    )
    from iris.llm.external.ollama import (  # pylint: disable=import-outside-toplevel
        convert_to_ollama_messages,
    )
    from iris.llm.external.openai_chat import (  # pylint: disable=import-outside-toplevel
        convert_content_to_openai_format,
        convert_content_to_responses_format,
    )

    content = JsonMessageContentDTO(
        jsonContent={"type": "mcq", "response": {"selectedIndex": 1}}
    )
    expected = '{"type": "mcq", "response": {"selectedIndex": 1}}'

    assert convert_content_to_openai_format(content) == {
        "type": "text",
        "text": expected,
    }
    assert convert_content_to_responses_format(content) == {
        "type": "input_text",
        "text": expected,
    }
    converted = convert_to_ollama_messages(
        [
            PyrisMessage(
                sender="LLM",
                contents=[content],
                sentAt="2026-05-16T10:00:00Z",
            )
        ]
    )
    assert converted[0].content == expected
    langchain_message = convert_iris_message_to_langchain_message(
        PyrisMessage(
            sender="LLM",
            contents=[TextMessageContentDTO(textContent="Prior quiz:"), content],
            sentAt="2026-05-16T10:00:00Z",
        )
    )
    assert langchain_message.content == f"Prior quiz:\n{expected}"


def test_checked_in_corpus_has_expected_coverage_and_valid_wire_contracts():
    suite = load_suite(
        QA_ROOT / "scenarios",
        QA_ROOT / "fixtures",
        QA_ROOT / "artifacts",
    )

    assert len(suite.scenarios) == 50
    assert Counter(scenario.use_case for scenario in suite.scenarios) == {
        UseCase.CHAT: 42,
        UseCase.TUTOR_SUGGESTION: 3,
        UseCase.AUTONOMOUS_TUTOR: 3,
        UseCase.GLOBAL_SEARCH: 2,
    }
    assert Counter(
        scenario.support_level
        for scenario in suite.scenarios
        if scenario.use_case == UseCase.CHAT
    ) == {"low": 14, "moderate": 14, "high": 14}
    for use_case in (UseCase.TUTOR_SUGGESTION, UseCase.AUTONOMOUS_TUTOR):
        assert {
            scenario.support_level
            for scenario in suite.scenarios
            if scenario.use_case == use_case
        } == {"low", "moderate", "high"}

    multi_turn_chat = [
        scenario
        for scenario in suite.scenarios
        if scenario.use_case == UseCase.CHAT
        and len(scenario.payload.get("chatHistory", [])) >= 3
    ]
    assert len(multi_turn_chat) >= 12
    assert {
        (scenario.mode, scenario.support_level) for scenario in multi_turn_chat
    } == {
        (mode, support)
        for mode in (
            "COURSE_CHAT",
            "LECTURE_CHAT",
            "PROGRAMMING_EXERCISE_CHAT",
            "TEXT_EXERCISE_CHAT",
        )
        for support in ("low", "moderate", "high")
    }

    contracts = validate_suite_contracts(suite.scenarios, qa_root=QA_ROOT)

    assert len(contracts) == 50
    tutor_contract = next(
        item for item in contracts if item.scenario_id == "tutor-copyable-reply"
    )
    assert "chatMode" not in tutor_contract.round_trip_payload
    assert set(tutor_contract.round_trip_payload) <= {
        "course",
        "post",
        "chatHistory",
        "user",
        "settings",
        "textExerciseDTO",
        "submission",
        "programmingExerciseDTO",
        "lectureId",
    }
    programming = next(
        item for item in suite.scenarios if item.id == "prog-compile-low"
    )
    assert programming.payload["programmingExercise"]["templateRepository"]
    assert programming.payload["programmingExercise"]["solutionRepository"]
    assert programming.payload["programmingExercise"]["testRepository"]
    compile_submission = programming.payload["programmingExerciseSubmission"]
    assert compile_submission["repository"]
    assert compile_submission["id"] == 501
    assert compile_submission["buildFailed"] is True
    assert compile_submission["latestResult"]["feedbacks"] == []
    assert [entry["message"] for entry in compile_submission["buildLogEntries"]] == [
        "src/Sort.java:[7,42] ';' expected",
        "src/Sort.java:[9,16] incompatible types: int[] cannot be converted to int",
    ]
    assert "recentChanges" not in programming.payload["programmingExercise"]
    assert "maxPoints" not in programming.payload["programmingExercise"]
    missing_lecture = next(
        item for item in suite.scenarios if item.id == "lecture-german-missing-low"
    )
    missing_retrieval = missing_lecture.payload["qa"]["retrieval"]
    assert missing_retrieval["currentView"] == {"pages": [], "transcript": []}
    assert missing_retrieval["search"] == []

    weekly = [item for item in suite.scenarios if "weekly" in item.profiles]
    assert len(weekly) == 33
    assert {
        (item.mode, item.support_level)
        for item in weekly
        if item.use_case == UseCase.CHAT
    } == {
        (mode, support)
        for mode in (
            "COURSE_CHAT",
            "LECTURE_CHAT",
            "PROGRAMMING_EXERCISE_CHAT",
            "TEXT_EXERCISE_CHAT",
        )
        for support in ("low", "moderate", "high")
    }
    assert {item.use_case for item in weekly} == set(UseCase)
    assert sum(item.risk == RiskLevel.CRITICAL for item in weekly) == 4


def test_global_search_limit_matches_artemis_maximum():
    suite = load_suite(
        QA_ROOT / "scenarios",
        QA_ROOT / "fixtures",
        QA_ROOT / "artifacts",
    )
    scenario = next(
        item for item in suite.scenarios if item.id == "global-grounded-answer"
    ).model_copy(deep=True)
    scenario.payload["limit"] = 6

    with pytest.raises(ScenarioContractError, match="limit must be 1..5"):
        validate_scenario_contract(scenario, qa_root=QA_ROOT)


def test_chat_history_requires_artemis_content_discriminator_and_timestamp():
    suite = load_suite(
        QA_ROOT / "scenarios",
        QA_ROOT / "fixtures",
        QA_ROOT / "artifacts",
    )
    scenario = next(
        item for item in suite.scenarios if item.id == "course-dashboard-low"
    ).model_copy(deep=True)
    scenario.payload["chatHistory"][0]["contents"][0].pop("type")

    with pytest.raises(ScenarioContractError, match="type discriminator"):
        validate_scenario_contract(scenario, qa_root=QA_ROOT)

    scenario = next(
        item for item in suite.scenarios if item.id == "course-dashboard-low"
    ).model_copy(deep=True)
    scenario.payload["chatHistory"][0].pop("sentAt")

    with pytest.raises(ScenarioContractError, match="sentAt is required"):
        validate_scenario_contract(scenario, qa_root=QA_ROOT)


def test_programming_submission_must_exist_in_recorded_history():
    suite = load_suite(
        QA_ROOT / "scenarios",
        QA_ROOT / "fixtures",
        QA_ROOT / "artifacts",
    )
    scenario = next(
        item for item in suite.scenarios if item.id == "prog-compile-low"
    ).model_copy(deep=True)
    scenario.payload["programmingExerciseSubmission"]["id"] = 999

    with pytest.raises(ScenarioContractError, match="absent from its history"):
        validate_scenario_contract(scenario, qa_root=QA_ROOT)


def test_programming_submission_must_match_recorded_snapshot():
    suite = load_suite(
        QA_ROOT / "scenarios",
        QA_ROOT / "fixtures",
        QA_ROOT / "artifacts",
    )
    scenario = next(
        item for item in suite.scenarios if item.id == "prog-compile-low"
    ).model_copy(deep=True)
    scenario.payload["programmingExerciseSubmission"]["repository"][
        "src/Sort.java"
    ] += "\n// drift"

    with pytest.raises(
        ScenarioContractError, match="differs from its history snapshot"
    ):
        validate_scenario_contract(scenario, qa_root=QA_ROOT)


def test_scenario_rejects_nonproduction_tool_name():
    suite = load_suite(
        QA_ROOT / "scenarios",
        QA_ROOT / "fixtures",
        QA_ROOT / "artifacts",
    )
    scenario = suite.scenarios[0].model_copy(deep=True)
    scenario.expectations.required_tools = ["memory_search"]

    with pytest.raises(ScenarioContractError, match="not production activities"):
        validate_scenario_contract(scenario, qa_root=QA_ROOT)


def test_scenario_rejects_missing_solution_oracle():
    suite = load_suite(
        QA_ROOT / "scenarios",
        QA_ROOT / "fixtures",
        QA_ROOT / "artifacts",
    )
    scenario = next(
        item for item in suite.scenarios if item.expectations.solution_files
    ).model_copy(deep=True)
    scenario.expectations.solution_files = ["programming/missing/Solution.java"]

    with pytest.raises(ScenarioContractError, match="solution file is missing"):
        validate_scenario_contract(scenario, qa_root=QA_ROOT)


def test_checked_in_expected_tools_match_production_callable_names():
    # Importing Memiris before the DTO modules are initialized creates a
    # production-package import cycle, so keep this introspection import local.
    from iris.common.memiris_setup import (  # pylint: disable=import-outside-toplevel
        MemirisWrapper,
    )

    factories = (
        create_tool_faq_content_retrieval,
        create_tool_file_lookup,
        create_tool_generate_mcq_questions,
        create_tool_get_build_logs_analysis,
        create_tool_get_competency_list,
        create_tool_get_example_solution,
        create_tool_get_feedbacks,
        create_tool_get_last_artifact,
        create_tool_get_student_exercise_metrics,
        create_tool_get_submission_details,
        create_tool_lecture_content_retrieval,
        create_tool_repository_files,
        MemirisWrapper.create_tool_memory_search,
        MemirisWrapper.create_tool_find_similar_memories,
    )
    production_names = set().union(
        *(_nested_callable_names(factory) for factory in factories)
    )
    suite = load_suite(
        QA_ROOT / "scenarios",
        QA_ROOT / "fixtures",
        QA_ROOT / "artifacts",
    )
    expected_names = {
        name
        for scenario in suite.scenarios
        for name in (
            scenario.expectations.required_tools
            + scenario.expectations.optional_tools
            + scenario.expectations.forbidden_tools
            + scenario.expectations.tool_order
        )
    }

    assert expected_names <= production_names
