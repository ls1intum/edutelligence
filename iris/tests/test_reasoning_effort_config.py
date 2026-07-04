import logging
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.tools import tool
from pydantic import ValidationError

import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.common.pyris_message import PyrisAIMessage, PyrisToolMessage
from iris.domain.data.text_message_content_dto import TextMessageContentDTO
from iris.domain.data.tool_call_dto import ToolCallDTO
from iris.domain.data.tool_message_content_dto import ToolMessageContentDTO
from iris.llm import CompletionArguments  # noqa: E402
from iris.llm.external.openai_chat import (  # noqa: E402
    AzureOpenAIChatModel,
    DirectOpenAIChatModel,
    convert_to_iris_message,
)
from iris.llm.llm_configuration import (  # noqa: E402
    LlmConfigurationError,
    validate_llm_configuration,
)


def _mock_openai_response():
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason="stop",
                message=SimpleNamespace(
                    role="assistant",
                    content="ok",
                    tool_calls=None,
                    refusal=None,
                ),
            )
        ],
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
    )


def _mock_responses_response(
    *,
    output=None,
    output_text="ok",
    input_tokens=1,
    output_tokens=1,
    status="completed",
):
    return SimpleNamespace(
        status=status,
        output=(
            output
            if output is not None
            else [
                SimpleNamespace(
                    type="message",
                    content=[
                        SimpleNamespace(
                            type="output_text",
                            text=output_text,
                        )
                    ],
                )
            ]
        ),
        output_text=output_text,
        usage=SimpleNamespace(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            output_tokens_details=SimpleNamespace(reasoning_tokens=0),
        ),
    )


def _build_model(**overrides):
    base = {
        "id": "test-model",
        "type": "openai_chat",
        "model": "gpt-test",
        "api_key": "sk-test",  # pragma: allowlist secret
        "supports_reasoning_effort": True,
    }
    base.update(overrides)
    return DirectOpenAIChatModel(**base)


def _build_azure_model(**overrides):
    base = {
        "id": "azure-test-model",
        "type": "azure_chat",
        "model": "gpt-test",
        "api_key": "sk-test",  # pragma: allowlist secret
        "api_version": "2025-04-01-preview",
        "azure_deployment": "gpt-test-deployment",
        "endpoint": "https://example.openai.azure.com",
        "supports_reasoning_effort": True,
    }
    base.update(overrides)
    return AzureOpenAIChatModel(**base)


def _invoke_chat(model, **completion_kwargs):
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _mock_openai_response()
    with patch.object(DirectOpenAIChatModel, "get_client", lambda self: mock_client):
        model.chat([], CompletionArguments(**completion_kwargs), tools=None)
    return mock_client.chat.completions.create.call_args.kwargs


@tool("lookup")
def _lookup(query: str) -> str:
    """Lookup data."""
    return query


def _sample_tool():
    return _lookup


def _sample_tool_schema():
    return {
        "type": "function",
        "function": {
            "name": "lookup",
            "description": "Lookup data.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    }


def _tool_call(call_id="call-1", query="weather"):
    return ToolCallDTO(
        id=call_id,
        function={
            "name": "lookup",
            "arguments": f'{{"query": "{query}"}}',
        },
    )


def _invoke_responses_chat(model, messages=None, tools=None, **completion_kwargs):
    mock_client = MagicMock()
    mock_client.responses.create.return_value = _mock_responses_response()
    with patch.object(type(model), "get_client", lambda self: mock_client):
        result = model.chat(
            messages or [],
            CompletionArguments(**completion_kwargs),
            tools=tools if tools is not None else [_sample_tool()],
        )
    return mock_client, result


def test_per_call_reasoning_effort_wins_over_entry_default():
    model = _build_model(reasoning_effort="low")
    params = _invoke_chat(model, reasoning_effort="high")
    assert params["reasoning_effort"] == "high"


def test_entry_default_reasoning_effort_is_used_when_per_call_is_none():
    model = _build_model(reasoning_effort="medium")
    params = _invoke_chat(model)
    assert params["reasoning_effort"] == "medium"


def test_reasoning_effort_is_omitted_when_call_and_entry_default_are_none():
    model = _build_model()
    params = _invoke_chat(model)
    assert "reasoning_effort" not in params


def test_reasoning_effort_is_clamped_to_nearest_allowed_value():
    model = _build_model(reasoning_effort_values=["low", "medium", "high"])

    assert _invoke_chat(model, reasoning_effort="none")["reasoning_effort"] == "low"
    assert _invoke_chat(model, reasoning_effort="xhigh")["reasoning_effort"] == "high"
    assert _invoke_chat(model, reasoning_effort="minimal")["reasoning_effort"] == "low"


def test_reasoning_effort_in_allowed_values_passes_through():
    model = _build_model(reasoning_effort_values=["low", "medium", "high"])
    params = _invoke_chat(model, reasoning_effort="medium")
    assert params["reasoning_effort"] == "medium"


def test_reasoning_effort_argument_is_dropped_when_model_does_not_support_it():
    model = _build_model(supports_reasoning_effort=False)
    params = _invoke_chat(model, reasoning_effort="high")
    assert "reasoning_effort" not in params


def test_reasoning_effort_clamp_logs_warning(caplog):
    model = _build_model(reasoning_effort_values=["low", "medium", "high"])

    with caplog.at_level(logging.WARNING, logger="iris.llm.external.openai_chat"):
        params = _invoke_chat(model, reasoning_effort="xhigh")

    assert params["reasoning_effort"] == "high"
    messages = [record.getMessage() for record in caplog.records]
    assert any(
        "Clamping reasoning_effort=xhigh to high for model id=test-model" in message
        for message in messages
    ), f"expected clamp warning; got: {messages}"


def test_responses_api_azure_uses_flattened_tools_reasoning_and_deployment_model():
    model = _build_azure_model(use_responses_api=True, reasoning_effort="medium")
    mock_client, _ = _invoke_responses_chat(
        model,
        tools=[_sample_tool_schema()],
        max_tokens=42,
        response_format="JSON",
    )

    mock_client.responses.create.assert_called_once()
    mock_client.chat.completions.create.assert_not_called()
    params = mock_client.responses.create.call_args.kwargs
    assert params["model"] == "gpt-test-deployment"
    assert params["reasoning"] == {"effort": "medium"}
    assert params["store"] is False
    assert params["max_output_tokens"] == 42
    assert params["text"] == {"format": {"type": "json_object"}}
    assert params["tools"] == [
        {
            "type": "function",
            "name": "lookup",
            "description": "Lookup data.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        }
    ]


def test_responses_api_tool_call_round_trip_matches_chat_shape():
    response_tool_call = SimpleNamespace(
        type="function_call",
        call_id="call-2",
        name="lookup",
        arguments='{"query": "next"}',
    )
    model = _build_model(use_responses_api=True, reasoning_effort="medium")
    mock_client = MagicMock()
    mock_client.responses.create.return_value = _mock_responses_response(
        output=[response_tool_call],
        output_text="",
    )
    assistant_message = PyrisAIMessage(
        toolCalls=[_tool_call()],
        contents=[TextMessageContentDTO(textContent="")],
    )
    tool_message = PyrisToolMessage(
        contents=[
            ToolMessageContentDTO(
                toolName="lookup",
                toolContent='{"result": "sunny"}',
                toolCallId="call-1",
            )
        ]
    )

    with patch.object(DirectOpenAIChatModel, "get_client", lambda self: mock_client):
        result = model.chat(
            [assistant_message, tool_message],
            CompletionArguments(),
            tools=[_sample_tool()],
        )

    params = mock_client.responses.create.call_args.kwargs
    assert params["input"] == [
        {
            "type": "function_call",
            "call_id": "call-1",
            "name": "lookup",
            "arguments": '{"query": "weather"}',
        },
        {
            "type": "function_call_output",
            "call_id": "call-1",
            "output": '{"result": "sunny"}',
        },
    ]
    expected = convert_to_iris_message(
        SimpleNamespace(
            role="assistant",
            content=None,
            tool_calls=[
                SimpleNamespace(
                    id="call-2",
                    type="function",
                    function=SimpleNamespace(
                        name="lookup",
                        arguments='{"query": "next"}',
                    ),
                )
            ],
        ),
        SimpleNamespace(prompt_tokens=1, completion_tokens=1),
        model.model,
    )
    assert isinstance(result, PyrisAIMessage)
    assert result.tool_calls == expected.tool_calls


def test_responses_api_usage_maps_to_token_usage_fields():
    model = _build_model(use_responses_api=True, reasoning_effort="medium")
    mock_client = MagicMock()
    mock_client.responses.create.return_value = _mock_responses_response(
        input_tokens=11,
        output_tokens=22,
    )

    with patch.object(DirectOpenAIChatModel, "get_client", lambda self: mock_client):
        result = model.chat([], CompletionArguments(), tools=None)

    assert result.token_usage.model_info == "gpt-test"
    assert result.token_usage.num_input_tokens == 11
    assert result.token_usage.num_output_tokens == 22


def test_responses_api_is_not_called_when_flag_is_off():
    model = _build_model(reasoning_effort="medium")
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _mock_openai_response()

    with patch.object(DirectOpenAIChatModel, "get_client", lambda self: mock_client):
        model.chat([], CompletionArguments(), tools=[_sample_tool()])

    mock_client.responses.create.assert_not_called()
    mock_client.chat.completions.create.assert_called_once()


def test_responses_api_reasoning_effort_is_clamped_to_nearest_allowed_value():
    model = _build_model(
        use_responses_api=True,
        reasoning_effort_values=["low", "medium", "high"],
    )
    mock_client, _ = _invoke_responses_chat(model, reasoning_effort="xhigh")

    params = mock_client.responses.create.call_args.kwargs
    assert params["reasoning"] == {"effort": "high"}


def test_missing_llm_catalog_id_raises_with_pipeline_variant_role_and_id():
    config = {
        "chat_pipeline": {
            "default": {
                "chat": {
                    "local": "known-model",
                    "cloud": "missing-model",
                },
            },
        },
    }

    with pytest.raises(LlmConfigurationError) as exc_info:
        validate_llm_configuration(config, known_model_ids={"known-model"})

    message = str(exc_info.value)
    assert "llm_configuration.chat_pipeline.default.chat.cloud" in message
    assert "missing-model" in message


def test_flat_missing_llm_catalog_id_raises_with_pipeline_variant_role_and_id():
    config = {
        "retrieval_pipeline": {
            "default": {
                "embedding": "missing-embedding",
            },
        },
    }

    with pytest.raises(LlmConfigurationError) as exc_info:
        validate_llm_configuration(config, known_model_ids={"known-model"})

    message = str(exc_info.value)
    assert "llm_configuration.retrieval_pipeline.default.embedding" in message
    assert "missing-embedding" in message


def test_bare_llm_configuration_validation_skips_catalog_cross_reference():
    config = {
        "chat_pipeline": {
            "default": {
                "chat": {
                    "local": "missing-model",
                    "cloud": "missing-model",
                },
            },
        },
    }

    validate_llm_configuration(config)


def test_reasoning_effort_default_must_be_in_declared_allowed_values():
    with pytest.raises(ValueError) as exc_info:
        _build_model(
            reasoning_effort="xhigh",
            reasoning_effort_values=["low", "medium", "high"],
        )

    assert "reasoning_effort=xhigh must be one of" in str(exc_info.value)


def test_reasoning_effort_default_requires_support_flag():
    with pytest.raises(ValueError) as exc_info:
        _build_model(supports_reasoning_effort=False, reasoning_effort="high")

    assert "supports_reasoning_effort must be true" in str(exc_info.value)


def test_reasoning_effort_values_require_support_flag():
    with pytest.raises(ValueError) as exc_info:
        _build_model(
            supports_reasoning_effort=False,
            reasoning_effort_values=["low", "medium", "high"],
        )

    assert "supports_reasoning_effort must be true" in str(exc_info.value)


def test_valid_reasoning_effort_model_entry_passes_validation():
    model = _build_model(
        reasoning_effort="medium",
        reasoning_effort_values=["low", "medium", "high"],
    )

    assert model.reasoning_effort == "medium"


def test_empty_reasoning_effort_values_is_rejected():
    with pytest.raises(ValidationError, match="must not be empty"):
        _build_model(reasoning_effort_values=[])


def test_null_entry_in_reasoning_effort_values_is_rejected():
    with pytest.raises(ValidationError):
        _build_model(reasoning_effort_values=["low", None])
