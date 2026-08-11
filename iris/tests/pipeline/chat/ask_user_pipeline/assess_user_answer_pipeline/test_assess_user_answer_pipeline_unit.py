from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate

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
    pipeline.llm.tokens = SimpleNamespace(pipeline=None)

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


# --------------------------------------------------------------------------
# prompt injection: exercise/submission data must not land in the system message
# --------------------------------------------------------------------------


def test_exercise_data_is_a_separate_human_message_not_in_the_system_message():
    """Student-controlled submission content (and the exercise template/description)
    must not be interpolated into the system message, since that is the model's
    highest-authority channel and a student could plant fake instructions in a file
    name or comment. It must instead be a separate, clearly delimited human message
    placed after the system message."""
    dto = _make_dto(questions_asked=3, min_questions=2, max_questions=5)

    pipeline = AssessUserAnswerPipeline()
    pipeline.llm = MagicMock()
    pipeline.llm.tokens = SimpleNamespace(pipeline=None)
    pipeline.pipeline = MagicMock()

    # Capture the *first* ChatPromptTemplate.from_messages(...) call (the one built
    # from the raw templates), while still using the real implementation so the
    # templates are genuinely rendered below - only the final LLM call is mocked.
    real_from_messages = ChatPromptTemplate.from_messages
    captured = {}

    def _capture(messages, *args, **kwargs):
        template = real_from_messages(messages, *args, **kwargs)
        captured.setdefault("first", template)
        return template

    with patch(
        "iris.pipeline.chat.assess_user_answer_pipeline.ChatPromptTemplate.from_messages",
        side_effect=_capture,
    ):
        pipeline(dto)

    rendered = captured["first"].format_messages(
        template="TEMPLATE_MARKER",
        task="TASK_MARKER",
        files="FILES_MARKER",
        decision_rules="RULES_MARKER",
    )

    assert isinstance(rendered[0], SystemMessage)
    assert "FILES_MARKER" not in rendered[0].content
    assert "TEMPLATE_MARKER" not in rendered[0].content
    assert "TASK_MARKER" not in rendered[0].content
    assert "RULES_MARKER" in rendered[0].content

    assert isinstance(rendered[1], HumanMessage)
    assert "FILES_MARKER" in rendered[1].content
    assert "TEMPLATE_MARKER" in rendered[1].content
    assert "TASK_MARKER" in rendered[1].content
    assert "<exercise_data>" in rendered[1].content
