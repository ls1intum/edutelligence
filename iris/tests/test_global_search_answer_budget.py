"""A global-search answer cut at its output budget is retried once, then given up.

A model that reasons before it answers can spend the whole budget on reasoning.
The Responses API then raises IncompleteModelResponse; Chat Completions return
empty text at the limit. Either way the student must still get the sources, and
every call must be billed once.
"""

# pylint: disable=protected-access

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.common.pyris_message import IrisMessageRole, PyrisMessage  # noqa: E402
from iris.common.token_usage_dto import TokenUsageDTO  # noqa: E402
from iris.domain.data.text_message_content_dto import (  # noqa: E402
    TextMessageContentDTO,
)
from iris.llm import CompletionArguments  # noqa: E402
from iris.llm.errors import IncompleteModelResponse  # noqa: E402
from iris.llm.langchain.iris_langchain_chat_model import (  # noqa: E402
    IrisLangchainChatModel,
)
from iris.llm.request_handler.request_handler_interface import (  # noqa: E402
    RequestHandler,
)
from iris.pipeline.global_search_pipeline import (  # noqa: E402
    ANSWER_MAX_TOKENS,
    RETRY_ANSWER_MAX_TOKENS,
    GlobalSearchPipeline,
)


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
        completion_args=CompletionArguments(max_tokens=ANSWER_MAX_TOKENS),
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


def _billed(pipeline):
    """Output tokens of every call: those billed inside, then the caller's."""
    return [t.num_output_tokens for t in pipeline.tokens] + [
        pipeline.answer_llm.tokens.num_output_tokens
    ]


def test_a_reasoning_only_cut_is_retried_with_a_larger_budget():
    pipeline, handler = _pipeline([_cut(600), _answer("Use the slides [1]", 900)])

    raw = pipeline._generate_answer("q", [])

    assert raw == "Use the slides [1]"
    assert handler.budgets == [ANSWER_MAX_TOKENS, RETRY_ANSWER_MAX_TOKENS]
    assert _billed(pipeline) == [600, 900]
    assert pipeline.answer_llm.completion_args.max_tokens == ANSWER_MAX_TOKENS


def test_empty_text_at_the_limit_is_retried_too():
    pipeline, handler = _pipeline(
        [_answer("", ANSWER_MAX_TOKENS), _answer("Answer [1]", 700)]
    )

    assert pipeline._generate_answer("q", []) == "Answer [1]"
    assert handler.budgets == [ANSWER_MAX_TOKENS, RETRY_ANSWER_MAX_TOKENS]
    assert _billed(pipeline) == [ANSWER_MAX_TOKENS, 700]


def test_a_second_cut_gives_no_answer_and_bills_both_calls():
    pipeline, handler = _pipeline([_cut(600), _cut(2400)])

    assert pipeline._generate_answer("q", []) == ""
    assert handler.budgets == [ANSWER_MAX_TOKENS, RETRY_ANSWER_MAX_TOKENS]
    assert _billed(pipeline) == [600, 2400]
    assert pipeline.answer_llm.completion_args.max_tokens == ANSWER_MAX_TOKENS


def test_empty_text_below_the_limit_is_not_retried():
    pipeline, handler = _pipeline([_answer("", 40)])

    assert pipeline._generate_answer("q", []) == ""
    assert handler.budgets == [ANSWER_MAX_TOKENS]
    assert not pipeline.tokens


def test_a_normal_answer_makes_one_call():
    pipeline, handler = _pipeline([_answer("!none!", 5)])

    assert pipeline._generate_answer("q", []) == "!none!"
    assert handler.budgets == [ANSWER_MAX_TOKENS]
    assert not pipeline.tokens


def test_the_client_drops_partial_text_before_the_retry():
    pipeline, _ = _pipeline([_cut(600), _answer("Answer [1]", 300)])
    events = []

    pipeline._generate_answer("q", [], stream_handler=events.append)

    assert None in events
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
