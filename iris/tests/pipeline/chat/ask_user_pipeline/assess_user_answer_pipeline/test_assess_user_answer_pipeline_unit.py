from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from iris.common.pipeline_enum import PipelineEnum
from iris.pipeline.chat.assess_user_answer_pipeline import AssessUserAnswerPipeline
from iris.pipeline.prompts.assess_user_answer_prompt import (
    between_min_max_questions_rules,
    over_equal_max_questions_rules,
    under_min_questions_rules,
)

RESPONSE_TEXT = '{"verdict": "NEXT_QUESTION", "reasoning": "Too vague."}'


class _FakeChain:
    """Stand-in for a ChatPromptTemplate that records format_messages() calls
    and short-circuits '|' composition so no real LLM is ever invoked."""

    def __init__(self, recorder):
        self.recorder = recorder

    def format_messages(self, **kwargs):
        self.recorder.append(kwargs)
        return ["formatted-prompt-val"]

    def __or__(self, _other):
        return self

    def invoke(self, _input):
        return RESPONSE_TEXT


def _make_dto(questions_asked, min_questions, max_questions):
    return SimpleNamespace(
        programming_exercise_submission=SimpleNamespace(
            repository={"Main.java": "class Main {}"}
        ),
        programming_exercise=SimpleNamespace(
            template_repository={"Main.java": "// TODO"},
            problem_statement="Implement Main.",
        ),
        chat_history=[],
        questions_asked=questions_asked,
        min_questions=min_questions,
        max_questions=max_questions,
    )


def _run(dto):
    pipeline = AssessUserAnswerPipeline()
    # The real llm/pipeline runnable would hit the network; format_messages()
    # capture below fully replaces the chain, so only .tokens needs a stand-in.
    pipeline.llm = MagicMock()

    recorder = []
    with patch(
        "iris.pipeline.chat.assess_user_answer_pipeline.ChatPromptTemplate.from_messages",
        side_effect=lambda *_a, **_kw: _FakeChain(recorder),
    ):
        response = pipeline(dto)

    return pipeline, response, recorder


def test_under_min_questions_uses_next_question_only_rules():
    dto = _make_dto(questions_asked=0, min_questions=2, max_questions=5)

    _pipeline, response, recorder = _run(dto)

    assert recorder[0]["decision_rules"] == under_min_questions_rules
    assert response == RESPONSE_TEXT


def test_at_max_questions_boundary_uses_over_equal_max_rules():
    # questions_asked == max_questions must already force a final verdict.
    dto = _make_dto(questions_asked=5, min_questions=2, max_questions=5)

    _pipeline, _response, recorder = _run(dto)

    assert recorder[0]["decision_rules"] == over_equal_max_questions_rules


def test_beyond_max_questions_uses_over_equal_max_rules():
    dto = _make_dto(questions_asked=6, min_questions=2, max_questions=5)

    _pipeline, _response, recorder = _run(dto)

    assert recorder[0]["decision_rules"] == over_equal_max_questions_rules


def test_between_min_and_max_uses_between_rules():
    dto = _make_dto(questions_asked=3, min_questions=2, max_questions=5)

    _pipeline, _response, recorder = _run(dto)

    assert recorder[0]["decision_rules"] == between_min_max_questions_rules


def test_at_min_questions_boundary_uses_between_rules():
    # questions_asked == min_questions is no longer "under min".
    dto = _make_dto(questions_asked=2, min_questions=2, max_questions=5)

    _pipeline, _response, recorder = _run(dto)

    assert recorder[0]["decision_rules"] == between_min_max_questions_rules


def test_formats_submission_and_template_files_with_names_and_content():
    dto = _make_dto(questions_asked=3, min_questions=2, max_questions=5)

    _pipeline, _response, recorder = _run(dto)

    assert recorder[0]["files"] == "Main.java:\nclass Main {}"
    assert recorder[0]["template"] == "Main.java:\n// TODO"
    assert recorder[0]["task"] == "Implement Main."


def test_tracks_token_usage_pipeline_enum_and_returns_response():
    dto = _make_dto(questions_asked=3, min_questions=2, max_questions=5)

    pipeline, response, _recorder = _run(dto)

    assert response == RESPONSE_TEXT
    assert pipeline.tokens.pipeline == PipelineEnum.IRIS_ASSESS_USER_ANSWER
