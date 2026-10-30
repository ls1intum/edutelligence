from jinja2 import Environment

import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.common.pipeline_enum import PipelineEnum
from iris.common.pyris_message import IrisMessageRole, PyrisMessage
from iris.common.token_usage_dto import TokenUsageDTO
from iris.domain.data.text_message_content_dto import TextMessageContentDTO
from iris.llm import CompletionArguments
from iris.llm.iris_chat_model import IrisChatModel
from iris.pipeline.session_title_generation_pipeline import (
    SessionTitleGenerationPipeline,
    TitleDecision,
)


class _Handler:
    """Returns a scripted JSON answer and records the request."""

    model_id = "title-model"

    def __init__(self, answer):
        self.answer = answer
        self.requests = []

    def chat(self, messages, arguments, tools):
        self.requests.append((messages, arguments, tools))
        return PyrisMessage(
            sender=IrisMessageRole.ASSISTANT,
            contents=[TextMessageContentDTO(textContent=self.answer)],
            token_usage=TokenUsageDTO(numInputTokens=3),
        )


def _pipeline(answer):
    pipeline = SessionTitleGenerationPipeline.__new__(SessionTitleGenerationPipeline)
    pipeline.prompt_template = Environment(autoescape=False).from_string(
        "Language: {{ language }}"
    )
    handler = _Handler(answer)
    pipeline.llm = IrisChatModel(handler, CompletionArguments(max_tokens=60))
    pipeline.tokens = None
    return pipeline, handler


def test_title_request_uses_the_schema_and_keeps_braces_as_data():
    pipeline, handler = _pipeline('{"decision": "keep", "title": null}')

    title_decision = pipeline(
        current_session_title="new chat",
        recent_messages=[
            'user: {"topic": "Vector DBs", "language": "en"}',
            "assistant: formatter edge case {foo!bar}",
        ],
    )

    assert title_decision == "KEEP"
    messages, arguments = handler.requests[0][:2]
    assert arguments.response_schema is TitleDecision
    assert '{"topic": "Vector DBs"' in messages[1].contents[0].text_content
    assert (
        pipeline.tokens.pipeline == PipelineEnum.IRIS_SESSION_TITLE_GENERATION_PIPELINE
    )


def test_update_decision_returns_the_new_title():
    pipeline = _pipeline('{"decision": "update", "title": "Binary Heaps"}')[0]

    assert pipeline("new chat", ["user: heaps?"]) == "UPDATE: Binary Heaps"


def test_update_without_a_title_keeps_the_old_one():
    pipeline = _pipeline('{"decision": "update", "title": "  "}')[0]

    assert pipeline("Heaps", ["user: heaps?"]) == "KEEP"


def test_invalid_output_is_no_title_change_and_still_billed():
    pipeline = _pipeline("UPDATE: Heaps")[0]

    assert pipeline("new chat", ["user: heaps?"]) is None
    assert pipeline.tokens.num_input_tokens == 3


def test_format_recent_messages_limits_and_truncates():
    recent_messages = [f"Message {i}: " + "x" * 500 for i in range(12)]
    formatted = SessionTitleGenerationPipeline.format_recent_messages(recent_messages)

    lines = formatted.splitlines()
    assert len(lines) == SessionTitleGenerationPipeline.MAX_RECENT_MESSAGES
    assert lines[0].startswith("1. Message 2:")
    assert lines[-1].startswith("10. Message 11:")
    assert lines[0].endswith("...")
