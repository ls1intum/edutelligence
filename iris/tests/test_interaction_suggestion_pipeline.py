"""Interaction suggestions come back as schema-validated JSON."""

import os

from jinja2 import Environment, FileSystemLoader

import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.common.pipeline_enum import PipelineEnum  # noqa: E402
from iris.common.pyris_message import IrisMessageRole, PyrisMessage  # noqa: E402
from iris.common.token_usage_dto import TokenUsageDTO  # noqa: E402
from iris.domain.chat.interaction_suggestion_dto import (  # noqa: E402
    InteractionSuggestionPipelineExecutionDTO,
)
from iris.domain.data.text_message_content_dto import TextMessageContentDTO
from iris.llm import CompletionArguments  # noqa: E402
from iris.llm.iris_chat_model import IrisChatModel  # noqa: E402
from iris.pipeline.chat import interaction_suggestion_pipeline as suggestion_module
from iris.pipeline.chat.interaction_suggestion_pipeline import (  # noqa: E402
    InteractionSuggestionPipeline,
    Questions,
)


class _Handler:
    """Returns a scripted answer and records the request."""

    model_id = "suggestion-model"

    def __init__(self, answer):
        self.answer = answer
        self.requests = []

    def chat(self, messages, arguments, tools):
        self.requests.append((messages, arguments, tools))
        return PyrisMessage(
            sender=IrisMessageRole.ASSISTANT,
            contents=[TextMessageContentDTO(textContent=self.answer)],
            token_usage=TokenUsageDTO(numInputTokens=4),
        )


def _pipeline(answer, variant="exercise"):
    pipeline = InteractionSuggestionPipeline.__new__(InteractionSuggestionPipeline)
    handler = _Handler(answer)
    pipeline.variant = variant
    pipeline.local = False
    pipeline.tokens = None
    pipeline.llm = IrisChatModel(handler, CompletionArguments())
    template_dir = os.path.join(
        os.path.dirname(suggestion_module.__file__), "..", "prompts", "templates"
    )
    pipeline.prompt_template = Environment(
        loader=FileSystemLoader(template_dir)
    ).get_template("interaction_suggestion_prompt.j2")
    return pipeline, handler


def _dto():
    dto = InteractionSuggestionPipelineExecutionDTO()
    dto.chat_history = [
        PyrisMessage(
            sender=IrisMessageRole.USER,
            contents=[TextMessageContentDTO(textContent="Why does my {sort} fail?")],
        )
    ]
    dto.last_message = "Look at the loop bound."
    dto.problem_statement = "Implement quicksort."
    return dto


def test_suggestions_are_requested_with_the_schema_and_returned():
    pipeline, handler = _pipeline(
        '{"questions": ["Why is the bound wrong?", "How do I test it?", "Third?"]}'
    )

    questions = pipeline(_dto(), language="German")

    assert questions == ["Why is the bound wrong?", "How do I test it?"]
    messages, arguments = handler.requests[0][:2]
    assert arguments.response_schema is Questions
    system = messages[0].contents[0].text_content
    assert "Implement quicksort." in system
    assert 'Use the "du" form.' in system
    assert messages[-2].sender == IrisMessageRole.ASSISTANT
    assert pipeline.tokens.pipeline == PipelineEnum.IRIS_INTERACTION_SUGGESTION


def test_invalid_output_returns_no_suggestions_but_keeps_usage():
    pipeline = _pipeline("Q: Why?")[0]

    assert pipeline(_dto()) == []
    assert pipeline.tokens.num_input_tokens == 4
