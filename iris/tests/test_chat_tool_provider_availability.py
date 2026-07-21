from types import SimpleNamespace
from unittest.mock import Mock

from iris.tools import chat_tool_providers as providers


def _state(**dto_fields):
    dto_defaults = {
        "course": SimpleNamespace(exercises=[], competencies=[]),
        "metrics": None,
        "programming_exercise": None,
        "text_exercise": None,
        "programming_exercise_submission": None,
    }
    dto_defaults.update(dto_fields)
    return SimpleNamespace(dto=SimpleNamespace(**dto_defaults), callback=Mock())


def test_data_backed_chat_tools_are_omitted_when_their_source_is_missing():
    state = _state()

    assert providers.provide_exercise_list(state) is None
    assert providers.provide_exercise_problem_statement(state) is None
    assert providers.provide_student_exercise_metrics(state) is None
    assert providers.provide_competency_list(state) is None
    assert providers.provide_submission_details(state) is None
    assert providers.provide_build_logs_analysis(state) is None
    assert providers.provide_feedbacks(state) is None
    assert providers.provide_repository_files(state) is None
    assert providers.provide_file_lookup(state) is None


def test_submission_tools_only_expose_evidence_that_artemis_supplied():
    submission = SimpleNamespace(
        repository={},
        latest_result=SimpleNamespace(feedbacks=[]),
    )
    state = _state(programming_exercise_submission=submission)

    assert providers.provide_submission_details(state) is not None
    assert providers.provide_build_logs_analysis(state) is not None
    assert providers.provide_feedbacks(state) is None
    assert providers.provide_repository_files(state) is None
    assert providers.provide_file_lookup(state) is None

    submission.repository = {"src/Main.java": "class Main {}"}
    submission.latest_result.feedbacks = [SimpleNamespace(text="failed")]

    assert providers.provide_feedbacks(state) is not None
    assert providers.provide_repository_files(state) is not None
    assert providers.provide_file_lookup(state) is not None


def test_metrics_tool_is_only_exposed_with_exercise_metrics():
    empty_metrics = SimpleNamespace(exercise_metrics=None)
    assert (
        providers.provide_student_exercise_metrics(_state(metrics=empty_metrics))
        is None
    )

    exercise_metrics = SimpleNamespace(
        average_score={},
        score={17: 7.0},
        average_latest_submission={17: 0.4},
        latest_submission={17: 0.5},
        completed={17},
    )
    state = _state(
        metrics=SimpleNamespace(exercise_metrics=exercise_metrics),
    )
    tool = providers.provide_student_exercise_metrics(state)

    assert tool is not None
    assert tool([17])[17]["score_of_student"] == 7.0
    assert tool([17])[17]["global_average_score"] is None
