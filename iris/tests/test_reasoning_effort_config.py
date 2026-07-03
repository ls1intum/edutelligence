import logging
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.llm import CompletionArguments  # noqa: E402
from iris.llm.external.openai_chat import DirectOpenAIChatModel  # noqa: E402
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


def _invoke_chat(model, **completion_kwargs):
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _mock_openai_response()
    with patch.object(DirectOpenAIChatModel, "get_client", lambda self: mock_client):
        model.chat([], CompletionArguments(**completion_kwargs), tools=None)
    return mock_client.chat.completions.create.call_args.kwargs


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
