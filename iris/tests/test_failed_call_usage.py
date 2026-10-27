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
from langchain_core.output_parsers import StrOutputParser

import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.common.pipeline_enum import PipelineEnum  # noqa: E402
from iris.common.token_usage_dto import TokenUsageDTO  # noqa: E402
from iris.llm import CompletionArguments  # noqa: E402
from iris.llm.errors import IncompleteModelResponse  # noqa: E402
from iris.llm.langchain import IrisLangchainChatModel  # noqa: E402
from iris.llm.request_handler.request_handler_interface import (  # noqa: E402
    RequestHandler,
)
from iris.pipeline import abstract_agent_pipeline  # noqa: E402
from iris.pipeline.chat.chat_pipeline import ChatPipeline  # noqa: E402
from iris.pipeline.shared import (  # noqa: E402
    citation_pipeline,
    mcq_generation_pipeline,
)
from iris.pipeline.shared.citation_pipeline import CitationPipeline  # noqa: E402
from iris.pipeline.shared.citation_sources import (  # noqa: E402
    CitationSourceRegistry,
)
from iris.pipeline.shared.mcq_generation_pipeline import (  # noqa: E402
    McqGenerationPipeline,
)
from tests.test_chat_compaction import (  # noqa: E402
    _compaction_state,
    _pipeline,
)
from tests.test_exercise_guide_refinement_modes import (  # noqa: E402
    _make_refinement_pipeline,
    _make_refinement_state,
    _make_variant,
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


def _cut_quiz_pipeline():
    """An MCQ pipeline whose model call stops at the output limit."""
    pipeline = McqGenerationPipeline.__new__(McqGenerationPipeline)
    pipeline.implementation_id = "mcq_generation_pipeline"
    pipeline.local = False
    pipeline.tokens = []
    pipeline.prompt_template = SimpleNamespace(render=lambda **_kwargs: "prompt")
    pipeline.llm = IrisLangchainChatModel(
        request_handler=_CutHandler(), completion_args=CompletionArguments()
    )
    pipeline.pipeline = pipeline.llm | StrOutputParser()
    return pipeline


def test_a_cut_guide_refinement_call_is_billed():
    pipeline = _make_refinement_pipeline()
    pipeline._resolve_guide_model = lambda _state: "guide-model"
    state = _make_refinement_state(_make_variant())

    with (
        patch(
            "iris.pipeline.chat.chat_pipeline.LlmRequestHandler",
            lambda **_kwargs: _CutHandler(),
        ),
        pytest.raises(IncompleteModelResponse),
    ):
        pipeline._run_guide_refinement(state, "The answer.")

    billed = pipeline._track_tokens.call_args.args[1]
    assert billed.num_output_tokens == 600


def test_a_cut_quiz_call_is_billed():
    pipeline = _cut_quiz_pipeline()

    with pytest.raises(IncompleteModelResponse):
        pipeline(command="One question about recursion")

    assert [t.num_output_tokens for t in pipeline.tokens] == [600]
    assert pipeline.tokens[0].pipeline == PipelineEnum.IRIS_MCQ_GENERATION_PIPELINE


def test_cut_quiz_workers_are_billed_when_no_question_comes_back():
    pipeline = _cut_quiz_pipeline()
    pipeline._extract_subtopics = lambda *_args, **_kwargs: ["a", "b"]

    with (
        patch.object(
            mcq_generation_pipeline,
            "McqGenerationPipeline",
            lambda local: _cut_quiz_pipeline(),
        ),
        pytest.raises(ValueError),
    ):
        pipeline.generate_set("Two questions about sorting", 2)

    # Two workers and two sequential retries, every one cut and billed.
    assert [t.num_output_tokens for t in pipeline.tokens] == [600] * 4
