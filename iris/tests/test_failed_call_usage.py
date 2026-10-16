"""Helper calls that stop early are still billed.

A response cut at its output limit raises IncompleteModelResponse. The call was
made, so its usage must reach the run's tokens: for the conversation
compaction, the citation labels and the quiz intro. The tests go through the
real model wrappers; only the request handler is a stub.
"""

# pylint: disable=protected-access

from types import SimpleNamespace
from unittest.mock import patch

import pytest

import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.common.pipeline_enum import PipelineEnum  # noqa: E402
from iris.common.token_usage_dto import TokenUsageDTO  # noqa: E402
from iris.llm.errors import IncompleteModelResponse  # noqa: E402
from iris.llm.iris_chat_model import IrisChatModel  # noqa: E402
from iris.llm.request_handler.request_handler_interface import (  # noqa: E402
    RequestHandler,
)
from iris.pipeline import abstract_agent_pipeline  # noqa: E402
from iris.pipeline.chat.chat_pipeline import ChatPipeline  # noqa: E402
from iris.pipeline.shared import citation_pipeline  # noqa: E402
from iris.pipeline.shared.citation_pipeline import CitationPipeline  # noqa: E402
from iris.pipeline.shared.citation_sources import (  # noqa: E402
    CitationSourceRegistry,
)
from tests.test_chat_compaction import (  # noqa: E402
    _compaction_state,
    _pipeline,
)


class _CutHandler(RequestHandler):
    """A request handler whose every chat call stops at the output limit."""

    output_tokens: int = 600

    def complete(self, prompt, arguments, image=None):
        raise NotImplementedError

    def chat(self, messages, arguments, tools):
        raise IncompleteModelResponse(
            "stopped",
            TokenUsageDTO(numInputTokens=900, numOutputTokens=self.output_tokens),
        )

    def embed(self, text):
        raise NotImplementedError

    def bind_tools(self, tools):
        return self


class _CallableTokens:
    def __init__(self, function):
        self.function = function
        self.tokens = []

    def __call__(self, *args, **kwargs):
        return self.function(*args, **kwargs)


def test_a_cut_compaction_call_is_billed():
    holder: dict = {}
    with patch.object(
        abstract_agent_pipeline, "LlmRequestHandler", lambda model_id: _CutHandler()
    ):
        _pipeline()._start_compaction(
            _compaction_state(prompt_tokens=2_000), holder
        ).join()

    assert "compaction" not in holder
    assert holder["tokens"].num_output_tokens == 600
    assert holder["tokens"].pipeline == PipelineEnum.IRIS_CHAT_COMPACTION


def _faq_registry() -> CitationSourceRegistry:
    registry = CitationSourceRegistry()
    registry.register_faq(
        {"faq_id": 1, "question_title": "Exam?", "question_answer": "Friday."}
    )
    return registry


def test_a_cut_citation_label_call_is_billed():
    pipeline = CitationPipeline.__new__(CitationPipeline)
    pipeline.tokens = []
    pipeline.label_prompt_str = "{language}\n{sources}"
    pipeline._label_model = "label-model"

    with patch.object(
        citation_pipeline, "LlmRequestHandler", lambda model_id: _CutHandler()
    ):
        result = pipeline("The exam is on Friday. [src:1]", _faq_registry())

    # The citation is still sent, only without keyword and summary.
    assert result == "The exam is on Friday. [cite:F:1:::::]"
    assert [t.num_output_tokens for t in pipeline.tokens] == [600]
    assert pipeline.tokens[0].pipeline == PipelineEnum.IRIS_CITATION_PIPELINE


def test_the_chat_bills_citation_calls_also_when_they_fail():
    pipeline = ChatPipeline.__new__(ChatPipeline)
    usage = TokenUsageDTO(numOutputTokens=600)

    def failing_citations(*_args, **_kwargs):
        pipeline.citation_pipeline.tokens.append(usage)
        raise IncompleteModelResponse("stopped", usage)

    pipeline.citation_pipeline = _CallableTokens(failing_citations)
    state = SimpleNamespace(
        tokens=[],
        answer_language="English",
        citation_sources=_faq_registry(),
        dto=SimpleNamespace(settings=None, user=SimpleNamespace(lang_key="en")),
    )

    result = pipeline._add_citations(state, "The answer. [src:1]")

    assert result == "The answer."
    assert usage in state.tokens


def test_a_cut_quiz_intro_is_billed():
    pipeline = ChatPipeline.__new__(ChatPipeline)
    pipeline.chat_mode = None
    llm = IrisChatModel(request_handler=_CutHandler())
    state = SimpleNamespace(
        mcq_parallel=True,
        llm=llm,
        prompt_messages=[],
        tokens=[],
        first_prompt_tokens=None,
    )

    with (
        patch.object(
            ChatPipeline,
            "get_token_pipeline",
            lambda self, state: PipelineEnum.IRIS_CHAT_COURSE_MESSAGE,
        ),
        pytest.raises(IncompleteModelResponse),
    ):
        pipeline.execute_agent(state)

    assert [t.num_output_tokens for t in state.tokens] == [600]
