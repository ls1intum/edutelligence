"""A global-search answer cut at its output budget gives no answer, not a failure.

A model that reasons before it answers can spend the whole budget on reasoning
when its llm_config entry has no reasoning_token_allowance. The Responses API
then raises IncompleteModelResponse; Chat Completions return empty text at the
limit. Either way the student must still get the sources, the call must be
billed once, and the log must name the missing setting.
"""

# pylint: disable=protected-access

import logging

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.common.pyris_message import IrisMessageRole, PyrisMessage  # noqa: E402
from iris.common.token_usage_dto import TokenUsageDTO  # noqa: E402
from iris.domain.data.text_message_content_dto import (  # noqa: E402
    TextMessageContentDTO,
)
from iris.domain.search.global_search_dto import (  # noqa: E402
    CourseInfo,
    LectureInfo,
    LectureSearchResultDTO,
    LectureUnitInfo,
)
from iris.domain.search.search_intent_dto import SearchIntent  # noqa: E402
from iris.llm import EMERGENCY_MAX_TOKENS, CompletionArguments  # noqa: E402
from iris.llm.errors import IncompleteModelResponse  # noqa: E402
from iris.llm.langchain.iris_langchain_chat_model import (  # noqa: E402
    IrisLangchainChatModel,
)
from iris.llm.request_handler.request_handler_interface import (  # noqa: E402
    RequestHandler,
)
from iris.pipeline.global_search_pipeline import GlobalSearchPipeline  # noqa: E402
from tests.test_global_search_entity_sources import _entity_source  # noqa: E402


class _ScriptedHandler(RequestHandler):
    """Returns or raises the scripted outcomes in order; records each budget."""

    outcomes: list = []
    budgets: list = []

    def complete(self, prompt, arguments, image=None):
        raise NotImplementedError

    def chat(self, messages, arguments, tools):
        self.budgets.append(arguments.max_tokens)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def embed(self, text):
        raise NotImplementedError

    def bind_tools(self, tools):
        return self


def _usage(output_tokens):
    return TokenUsageDTO(model="m", numInputTokens=100, numOutputTokens=output_tokens)


def _answer(text, output_tokens):
    return PyrisMessage(
        sender=IrisMessageRole.ASSISTANT,
        contents=[TextMessageContentDTO(textContent=text)],
        token_usage=_usage(output_tokens),
    )


def _cut(output_tokens):
    return IncompleteModelResponse("stopped", _usage(output_tokens))


def _pipeline(outcomes):
    handler = _ScriptedHandler(outcomes=list(outcomes), budgets=[])
    pipeline = GlobalSearchPipeline.__new__(GlobalSearchPipeline)
    pipeline.tokens = []
    pipeline.answer_llm = IrisLangchainChatModel(
        request_handler=handler,
        completion_args=CompletionArguments(max_tokens=EMERGENCY_MAX_TOKENS),
    )
    pipeline.answer_pipeline = pipeline.answer_llm | StrOutputParser()
    prompt = ChatPromptTemplate.from_messages(
        [("user", "{context} {query}{today_line}")]
    )
    pipeline.answer_prompt = prompt
    pipeline.navigate_prompt = ChatPromptTemplate.from_messages(
        [("user", "{context} {query}")]
    )
    return pipeline, handler


def test_a_cut_answer_gives_no_answer_and_bills_the_call(caplog):
    pipeline, handler = _pipeline([_cut(600)])

    with caplog.at_level(logging.WARNING):
        raw = pipeline._generate_answer("q", [])

    assert raw == ""
    assert handler.budgets == [EMERGENCY_MAX_TOKENS]
    # The caller bills answer_llm.tokens: it must be the cut call's usage.
    assert pipeline.answer_llm.tokens.num_output_tokens == 600
    assert not pipeline.tokens
    assert "emergency output limit" in caplog.text


def test_empty_text_at_the_limit_is_logged_with_the_setting(caplog):
    pipeline, handler = _pipeline([_answer("", EMERGENCY_MAX_TOKENS)])

    with caplog.at_level(logging.WARNING):
        assert pipeline._generate_answer("q", []) == ""

    assert handler.budgets == [EMERGENCY_MAX_TOKENS]
    assert "emergency output limit" in caplog.text


def test_empty_text_below_the_limit_is_not_reported_as_a_cut(caplog):
    pipeline, _ = _pipeline([_answer("", 40)])

    with caplog.at_level(logging.WARNING):
        assert pipeline._generate_answer("q", []) == ""

    assert "reasoning_token_allowance" not in caplog.text


def test_a_normal_answer_makes_one_call():
    pipeline, handler = _pipeline([_answer("!none!", 5)])

    assert pipeline._generate_answer("q", []) == "!none!"
    assert handler.budgets == [EMERGENCY_MAX_TOKENS]
    assert pipeline.answer_llm.tokens.num_output_tokens == 5


def test_the_client_drops_partial_text_of_a_cut_answer():
    pipeline, _ = _pipeline([_cut(600)])
    events = []

    pipeline._generate_answer("q", [], stream_handler=events.append)

    assert events == [None]
    assert pipeline.answer_llm.completion_args.stream_handler is None


def test_the_wrapper_reports_the_usage_of_a_cut_call_not_the_previous_one():
    pipeline, _ = _pipeline([_answer("first", 10), _cut(600)])
    pipeline.answer_llm.invoke("hi")
    assert pipeline.answer_llm.tokens.num_output_tokens == 10

    try:
        pipeline.answer_llm.invoke("hi")
    except IncompleteModelResponse:
        pass

    assert pipeline.answer_llm.tokens.num_output_tokens == 600


def test_a_cut_without_usage_reports_zero_tokens():
    pipeline, _ = _pipeline([_answer("first", 10), IncompleteModelResponse("x")])
    pipeline.answer_llm.invoke("hi")

    try:
        pipeline.answer_llm.invoke("hi")
    except IncompleteModelResponse:
        pass

    assert pipeline.answer_llm.tokens.num_output_tokens == 0


# Through the whole pipeline call: a cut answer shows the retrieved sources.


def _lecture(unit_id):
    return LectureSearchResultDTO(
        course=CourseInfo(id=1, name="Algorithms"),
        lecture=LectureInfo(id=2, name="Sorting"),
        lectureUnit=LectureUnitInfo(
            id=unit_id,
            name=f"Slides {unit_id}",
            link=f"/l{unit_id}",
            pageNumber=1,
            sourceType="lecture_unit_slide",
        ),
        snippet=f"Content {unit_id}.",
    )


def _entity():
    return _entity_source(title="Sorting exercise")


def _run(sources, outcomes):
    pipeline, handler = _pipeline(outcomes)
    pipeline._retrieve_sources = lambda *args, **kwargs: sources
    events = []
    response = pipeline(
        query="how does merge sort work?",
        intent=SearchIntent.TRIGGER_AI,
        base_url="http://a",
        stream_handler=events.append,
    )
    return response, pipeline, handler, events


def test_a_cut_answer_returns_the_lecture_sources_without_an_answer():
    sources = [_lecture(3), _lecture(4)]
    response, pipeline, handler, events = _run(sources, [_cut(600)])

    assert response.answer is None
    assert response.sources == sources
    assert response.entity_sources == []
    assert len(handler.budgets) == 1
    assert [t.num_output_tokens for t in pipeline.tokens] == [600]
    assert None in events


def test_a_cut_answer_with_entity_sources_skips_the_navigation_call():
    lecture, entity = _lecture(3), _entity()
    response, pipeline, handler, _ = _run(
        [lecture, entity], [_answer("", EMERGENCY_MAX_TOKENS)]
    )

    assert response.answer is None
    assert response.sources == [lecture]
    assert response.entity_sources == [entity]
    assert len(handler.budgets) == 1
    assert len(pipeline.tokens) == 1


def test_a_deliberate_no_answer_still_returns_no_sources():
    response, _, handler, _ = _run([_lecture(3)], [_answer("!none!", 5)])

    assert response.answer is None
    assert response.sources == []
    assert len(handler.budgets) == 1
