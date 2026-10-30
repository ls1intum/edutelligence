"""Model calls are Langfuse generations with the model name and token counts."""

from unittest.mock import Mock, patch

import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.common.token_usage_dto import TokenUsageDTO  # noqa: E402
from iris.tracing.langfuse_tracer import record_generation  # noqa: E402

TRACER = "iris.tracing.langfuse_tracer"


def _usage(input_tokens=120, output_tokens=30):
    return TokenUsageDTO(
        model="m", numInputTokens=input_tokens, numOutputTokens=output_tokens
    )


def test_the_generation_gets_the_model_and_the_token_counts():
    client = Mock()
    with (
        patch(f"{TRACER}._is_enabled", return_value=True),
        patch(f"{TRACER}.get_langfuse_client", return_value=client),
    ):
        record_generation("gpt-x", _usage())

    client.update_current_generation.assert_called_once_with(
        model="gpt-x", usage_details={"input": 120, "output": 30}
    )


def test_a_call_without_usage_records_only_the_model():
    client = Mock()
    with (
        patch(f"{TRACER}._is_enabled", return_value=True),
        patch(f"{TRACER}.get_langfuse_client", return_value=client),
    ):
        record_generation("gpt-x", None)

    client.update_current_generation.assert_called_once_with(
        model="gpt-x", usage_details=None
    )


def test_nothing_is_recorded_when_tracing_is_off():
    client = Mock()
    with (
        patch(f"{TRACER}._is_enabled", return_value=False),
        patch(f"{TRACER}.get_langfuse_client", return_value=client),
    ):
        record_generation("gpt-x", _usage())

    client.update_current_generation.assert_not_called()


def test_a_tracing_error_does_not_reach_the_caller():
    client = Mock()
    client.update_current_generation.side_effect = RuntimeError("no span")
    with (
        patch(f"{TRACER}._is_enabled", return_value=True),
        patch(f"{TRACER}.get_langfuse_client", return_value=client),
    ):
        record_generation("gpt-x", _usage())


def test_an_openai_call_is_one_generation_with_usage():
    """langfuse.openai already records each request as a generation with model
    and usage; the outer span must not record a second one. Real SDK, fake
    HTTP transport, spans collected in memory."""
    # pylint: disable=import-outside-toplevel
    import httpx
    from langfuse import Langfuse
    from opentelemetry import trace
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    from iris.common.pyris_message import IrisMessageRole, PyrisMessage
    from iris.domain.data.text_message_content_dto import TextMessageContentDTO
    from iris.llm import CompletionArguments
    from iris.llm.external.openai_chat import DirectOpenAIChatModel, OpenAI

    client = Langfuse(
        public_key="pk-lf-test",  # pragma: allowlist secret
        secret_key="sk-lf-test",  # pragma: allowlist secret
        host="http://127.0.0.1:9",
    )
    exporter = InMemorySpanExporter()
    trace.get_tracer_provider().add_span_processor(SimpleSpanProcessor(exporter))

    def completion(request):  # pylint: disable=unused-argument
        return httpx.Response(
            200,
            json={
                "id": "c1",
                "object": "chat.completion",
                "created": 0,
                "model": "gpt-x",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "hi"},
                    }
                ],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 20,
                    "total_tokens": 120,
                },
            },
        )

    model = DirectOpenAIChatModel(
        id="x",
        type="openai_chat",
        model="gpt-x",
        api_key="sk-test",  # pragma: allowlist secret
    )
    model._client = OpenAI(  # pylint: disable=protected-access
        api_key="sk-test",  # pragma: allowlist secret
        base_url="http://fake/v1",
        http_client=httpx.Client(transport=httpx.MockTransport(completion)),
        max_retries=0,
    )
    message = PyrisMessage(
        sender=IrisMessageRole.USER,
        contents=[TextMessageContentDTO(textContent="hello")],
    )
    with (
        patch(f"{TRACER}._is_enabled", return_value=True),
        patch(f"{TRACER}._langfuse_client", client),
        patch(f"{TRACER}._is_initialized", True),
    ):
        model.chat([message], CompletionArguments(), None)

    usage_generations = [
        span
        for span in exporter.get_finished_spans()
        if span.attributes.get("langfuse.observation.type") == "generation"
        and span.attributes.get("langfuse.observation.usage_details")
    ]
    assert len(usage_generations) == 1
