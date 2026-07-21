import importlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

# Establish the production package import order before importing DTOs.
importlib.import_module("iris.pipeline.pipeline")

from iris.domain.chat.chat_pipeline_execution_dto import (  # noqa: E402
    ChatPipelineExecutionDTO,
)
from iris.domain.communication.communication_tutor_suggestion_pipeline_execution_dto import (  # noqa: E402
    CommunicationTutorSuggestionPipelineExecutionDTO,
)
from iris.qa.adapters import FixtureMemiris, ScenarioAdapters  # noqa: E402
from iris.qa.loader import load_suite  # noqa: E402
from iris.tools import chat_tool_providers as providers  # noqa: E402
from iris.tools import (  # noqa: E402
    create_tool_get_additional_exercise_details,
    create_tool_get_last_artifact,
)

QA_ROOT = Path(__file__).parents[1] / "qa"


def _suite():
    return load_suite(
        QA_ROOT / "scenarios", QA_ROOT / "fixtures", QA_ROOT / "artifacts"
    )


def _chat(scenario_id: str):
    scenario = next(item for item in _suite().scenarios if item.id == scenario_id)
    payload = dict(scenario.payload)
    metadata = payload.pop("qa", {}) or {}
    return ChatPipelineExecutionDTO.model_validate(payload), metadata


def _state(dto, metadata: dict):
    retrieval = metadata.get("retrieval", {})
    FixtureMemiris.metadata = metadata
    return SimpleNamespace(
        dto=dto,
        callback=Mock(),
        db=SimpleNamespace(client=object()),
        query_text="fixture query",
        message_history=dto.chat_history,
        lecture_content_storage={},
        faq_storage={},
        local=False,
        accessed_memory_storage=[],
        allow_lecture_tool=bool(retrieval.get("lectureAvailable")),
        allow_faq_tool=bool(retrieval.get("faqAvailable")),
        allow_memiris_tool=bool(metadata.get("memories")),
        memiris_wrapper=FixtureMemiris(),
    )


def test_programming_fixture_executes_production_repository_feedback_and_log_tools():
    secret_dto, secret_metadata = _chat("prog-secret-log-high")
    feedback_dto, feedback_metadata = _chat("prog-failed-test-moderate")
    compile_dto, compile_metadata = _chat("prog-compile-low")

    with ScenarioAdapters(secret_metadata):
        state = _state(secret_dto, secret_metadata)
        build_logs = providers.provide_build_logs_analysis(state)()
        repository = providers.provide_repository_files(state)()
        source = providers.provide_file_lookup(state)("src/Sort.java")
        submission = providers.provide_submission_details(state)()

    assert "sk-qa-fixture-never-real-123456" not in build_logs
    assert "[REDACTED_API_KEY]" in build_logs
    assert "src/Sort.java" in repository
    assert "class Sort" in source
    assert submission["build_failed"] == "True"

    with ScenarioAdapters(feedback_metadata):
        feedback = providers.provide_feedbacks(
            _state(feedback_dto, feedback_metadata)
        )()
    assert "sortsDuplicatesAndNegativeValues" in feedback
    assert "Expected [-1, 0, 3, 3]" in feedback

    with ScenarioAdapters(compile_metadata):
        compile_feedback_tool = providers.provide_feedbacks(
            _state(compile_dto, compile_metadata)
        )
        assert callable(compile_feedback_tool)


def test_course_fixture_executes_production_metrics_and_competency_tools():
    dto, metadata = _chat("course-study-plan-high")
    with ScenarioAdapters(metadata):
        state = _state(dto, metadata)
        exercise_metrics = providers.provide_student_exercise_metrics(state)([9001])
        competencies = providers.provide_competency_list(state)()

    assert 9001 in exercise_metrics
    assert exercise_metrics[9001]["score_of_student"] == 6.0
    assert competencies
    by_title = {item["info"].title: item for item in competencies}
    assert by_title["Sorting Algorithms"]["mastery"] == 36
    assert by_title["Graph Traversal"]["mastery"] == 11


def test_scenario_adapter_freezes_prompt_and_deadline_time():
    from iris.pipeline import (  # pylint: disable=import-outside-toplevel
        autonomous_tutor_pipeline,
        tutor_suggestion_pipeline,
    )
    from iris.pipeline.chat import (  # pylint: disable=import-outside-toplevel
        chat_pipeline,
    )

    dto, metadata = _chat("prog-compile-low")
    with ScenarioAdapters(metadata):
        prompt_time = chat_pipeline.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        tutor_time = tutor_suggestion_pipeline.get_current_utc_datetime_string()
        autonomous_time = autonomous_tutor_pipeline.get_current_utc_datetime_string()
        deadline = create_tool_get_additional_exercise_details(
            dto.programming_exercise, Mock()
        )()

    assert prompt_time == "2026-05-17 12:00:00"
    assert tutor_time == prompt_time
    assert autonomous_time == prompt_time
    assert deadline["due_date_over"] is False


def test_retrieval_and_memory_fixtures_execute_production_tool_wrappers():
    faq_dto, faq_metadata = _chat("course-faq-moderate")
    with ScenarioAdapters(faq_metadata):
        faq_state = _state(faq_dto, faq_metadata)
        faq_output = providers.provide_faq_retrieval(faq_state)()
    assert "24-hour grace period" in faq_output
    assert faq_state.faq_storage["faqs"]

    lecture_dto, lecture_metadata = _chat("lecture-retrieval-high")
    with ScenarioAdapters(lecture_metadata):
        lecture_state = _state(lecture_dto, lecture_metadata)
        lecture_output = providers.provide_lecture_retrieval(lecture_state)()
    assert "Master Theorem" in lecture_output
    assert lecture_state.lecture_content_storage["content"]

    memory_dto, memory_metadata = _chat("course-memory-low")
    with ScenarioAdapters(memory_metadata):
        memory_tool = providers.provide_memory_search(
            _state(memory_dto, memory_metadata)
        )
        assert memory_tool is not None
        memory_output = memory_tool("learning preference")
    assert "small traced examples" in memory_output


def test_mcq_and_tutor_artifact_fixtures_execute_production_tool_wrappers():
    dto, metadata = _chat("course-one-mcq-moderate")

    class FakeMcqPipeline:
        def __call__(self, **kwargs):
            assert kwargs["user_language"] == "en"
            return json.dumps(
                {
                    "type": "mcq",
                    "question": "Which invariant holds?",
                    "options": [
                        {"text": "A sorted prefix", "correct": True},
                        {"text": "An empty input", "correct": False},
                        {"text": "Equal keys", "correct": False},
                        {"text": "No loop", "correct": False},
                    ],
                    "explanation": "The processed prefix remains sorted.",
                }
            )

    with ScenarioAdapters(metadata):
        state = _state(dto, metadata)
        state.mcq_pipeline = FakeMcqPipeline()
        mcq_tool = providers.provide_mcq_generation(state)
        assert mcq_tool is not None
        assert mcq_tool("Generate one sorting question") == "[MCQ_RESULT]"
    assert json.loads(state.mcq_result_storage["mcq_json"])["type"] == "mcq"

    scenario = next(
        item for item in _suite().scenarios if item.id == "tutor-regeneration"
    )
    payload = dict(scenario.payload)
    payload.pop("qa", None)
    tutor_dto = CommunicationTutorSuggestionPipelineExecutionDTO.model_validate(payload)
    artifact = create_tool_get_last_artifact(tutor_dto.chat_history, Mock())()
    assert "checked the loop boundary" in artifact
