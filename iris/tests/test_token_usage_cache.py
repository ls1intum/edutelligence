from types import SimpleNamespace

from openai.types import CompletionUsage  # noqa: E402
from openai.types.chat import ChatCompletionMessage  # noqa: E402
from openai.types.responses import ResponseUsage  # noqa: E402

# Bootstrap the iris package in the order the pipelines use (see
# test_openai_chat_reasoning_effort.py for the circular-import background).
import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.common.pipeline_enum import PipelineEnum  # noqa: E402
from iris.common.pyris_message import IrisMessageRole, PyrisMessage  # noqa: E402
from iris.common.token_usage_dto import TokenUsageDTO  # noqa: E402
from iris.domain.data.text_message_content_dto import (  # noqa: E402
    TextMessageContentDTO,
)
from iris.llm import CompletionArguments  # noqa: E402
from iris.llm.external.openai_chat import (  # noqa: E402
    DirectOpenAIChatModel,
    convert_responses_to_iris_message,
    convert_to_iris_message,
    create_token_usage,
)
from iris.llm.langchain.iris_langchain_chat_model import (  # noqa: E402
    IrisLangchainChatModel,
)
from iris.llm.request_handler.llm_request_handler import (  # noqa: E402
    apply_model_costs,
)
from iris.llm.request_handler.request_handler_interface import (  # noqa: E402
    RequestHandler,
)


class _StubRequestHandler(RequestHandler):
    """Minimal RequestHandler whose chat() returns a preset message."""

    next_message: object = None

    def complete(self, prompt, arguments, image=None):
        raise NotImplementedError

    def chat(self, messages, arguments, tools):
        return self.next_message

    def embed(self, text):
        raise NotImplementedError

    def bind_tools(self, tools):
        return self


def _model(**overrides):
    base = {
        "id": "gpt-6-luna",
        "type": "openai_chat",
        "model": "gpt-6-luna",
        "api_key": "sk-test",  # pragma: allowlist secret
        "cost_per_million_input_token": 0.10,
        "cost_per_million_cached_input_token": 0.01,
        "cost_per_million_cache_write_input_token": 0.125,
        "cost_per_million_output_token": 0.50,
    }
    base.update(overrides)
    return DirectOpenAIChatModel(**base)


def test_chat_completions_usage_reports_cache_reads_and_writes():
    usage = CompletionUsage(
        prompt_tokens=1566,
        completion_tokens=1518,
        total_tokens=3084,
        prompt_tokens_details={"cached_tokens": 1408, "cache_write_tokens": 128},
    )

    tokens = create_token_usage(usage, "gpt-6-luna")

    assert tokens.num_input_tokens == 1566
    assert tokens.num_output_tokens == 1518
    assert tokens.num_cached_input_tokens == 1408
    assert tokens.num_cache_write_input_tokens == 128


def test_responses_usage_reports_cache_reads_and_writes():
    usage = ResponseUsage.model_validate(
        {
            "input_tokens": 2048,
            "input_tokens_details": {"cached_tokens": 1920, "cache_write_tokens": 64},
            "output_tokens": 10,
            "output_tokens_details": {"reasoning_tokens": 0},
            "total_tokens": 2058,
        }
    )

    tokens = create_token_usage(usage, "gpt-6-luna")

    assert tokens.num_input_tokens == 2048
    assert tokens.num_output_tokens == 10
    assert tokens.num_cached_input_tokens == 1920
    assert tokens.num_cache_write_input_tokens == 64


def test_usage_without_details_counts_no_cached_tokens():
    tokens = create_token_usage(
        SimpleNamespace(prompt_tokens=7, completion_tokens=4), "gpt-5.4-mini"
    )

    assert tokens.num_input_tokens == 7
    assert tokens.num_cached_input_tokens == 0
    assert tokens.num_cache_write_input_tokens == 0


def test_usage_given_as_dict_is_read():
    tokens = create_token_usage(
        {
            "input_tokens": 5,
            "output_tokens": 2,
            "input_tokens_details": {"cached_tokens": 3},
        },
        "gpt-6-luna",
    )

    assert tokens.num_input_tokens == 5
    assert tokens.num_cached_input_tokens == 3
    assert tokens.num_cache_write_input_tokens == 0


def test_missing_usage_counts_zero():
    tokens = create_token_usage(None, "gpt-6-luna")

    assert tokens.num_input_tokens == 0
    assert tokens.num_cached_input_tokens == 0


def test_chat_completion_message_keeps_cached_tokens():
    message = ChatCompletionMessage(role="assistant", content="hi")
    usage = CompletionUsage(
        prompt_tokens=100,
        completion_tokens=5,
        total_tokens=105,
        prompt_tokens_details={"cached_tokens": 64},
    )

    result = convert_to_iris_message(message, usage, "gpt-5.4-mini")

    assert result.token_usage.num_cached_input_tokens == 64


def test_responses_message_keeps_cached_tokens():
    response = SimpleNamespace(
        output=[],
        output_text="hi",
        status="completed",
        usage=SimpleNamespace(
            input_tokens=100,
            output_tokens=5,
            input_tokens_details=SimpleNamespace(
                cached_tokens=96, cache_write_tokens=4
            ),
        ),
    )

    result = convert_responses_to_iris_message(response, "gpt-6-luna")

    assert result.token_usage.num_input_tokens == 100
    assert result.token_usage.num_cached_input_tokens == 96
    assert result.token_usage.num_cache_write_input_tokens == 4


def test_model_costs_include_cache_rates():
    tokens = TokenUsageDTO(numInputTokens=1000, numCachedInputTokens=900)

    apply_model_costs(tokens, _model())

    assert tokens.model_info == "gpt-6-luna"
    assert tokens.cost_per_million_input_token == 0.10
    assert tokens.cost_per_million_cached_input_token == 0.01
    assert tokens.cost_per_million_cache_write_input_token == 0.125
    assert tokens.cost_per_million_output_token == 0.50


def test_model_costs_use_long_context_tier_above_threshold():
    model = _model(
        long_context_threshold_tokens=272_000,
        long_context_input_cost_multiplier=2.0,
        long_context_output_cost_multiplier=1.5,
    )
    below = TokenUsageDTO(numInputTokens=272_000)
    above = TokenUsageDTO(numInputTokens=272_001)

    apply_model_costs(below, model)
    apply_model_costs(above, model)

    assert below.cost_per_million_input_token == 0.10
    assert above.cost_per_million_input_token == 0.20
    assert above.cost_per_million_cached_input_token == 0.02
    assert above.cost_per_million_cache_write_input_token == 0.25
    assert above.cost_per_million_output_token == 0.75


def test_langchain_wrapper_keeps_cache_counts_and_rates():
    usage = TokenUsageDTO(
        model="gpt-6-luna",
        numInputTokens=1000,
        numCachedInputTokens=900,
        numCacheWriteInputTokens=50,
        costPerMillionCachedInputToken=0.01,
        costPerMillionCacheWriteInputToken=0.125,
        pipelineId=PipelineEnum.IRIS_CHAT_COURSE_MESSAGE,
    )
    handler = _StubRequestHandler()
    handler.next_message = PyrisMessage(
        sender=IrisMessageRole.ASSISTANT,
        contents=[TextMessageContentDTO(textContent="answer")],
        token_usage=usage,
    )
    llm = IrisLangchainChatModel(
        request_handler=handler, completion_args=CompletionArguments()
    )

    llm._generate(messages=[])  # pylint: disable=protected-access

    assert llm.tokens.num_cached_input_tokens == 900
    assert llm.tokens.num_cache_write_input_tokens == 50
    assert llm.tokens.cost_per_million_cached_input_token == 0.01
    assert llm.tokens.cost_per_million_cache_write_input_token == 0.125
    assert llm.tokens.pipeline == PipelineEnum.NOT_SET


def test_token_usage_serializes_cache_fields_for_artemis():
    payload = TokenUsageDTO(
        numInputTokens=10,
        numCachedInputTokens=8,
        numCacheWriteInputTokens=1,
        costPerMillionCachedInputToken=0.01,
        costPerMillionCacheWriteInputToken=0.125,
    ).model_dump(by_alias=True)

    assert payload["numCachedInputTokens"] == 8
    assert payload["numCacheWriteInputTokens"] == 1
    assert payload["costPerMillionCachedInputToken"] == 0.01
    assert payload["costPerMillionCacheWriteInputToken"] == 0.125
