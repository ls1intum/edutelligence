# pylint: disable=protected-access
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from memiris.llm.ollama_language_model import OllamaLanguageModel
from memiris.llm.openai_language_model import OpenAiLanguageModel

QWEN_THINKING = {"chat_template_kwargs": {"enable_thinking": True}}


def _openai_model(**kwargs) -> tuple[OpenAiLanguageModel, MagicMock]:
    model = OpenAiLanguageModel(
        api_key="sk-test",  # pragma: allowlist secret
        base_url="https://logos.example/v1",
        **kwargs,
    )
    client = MagicMock()
    client.chat.completions.create.return_value = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(role="assistant", content="[]", tool_calls=None)
            )
        ],
        model=kwargs["model"],
    )
    model._client = client
    return model, client


def _sent(model_and_client: tuple[OpenAiLanguageModel, MagicMock]) -> dict:
    model, client = model_and_client
    model.chat([{"role": "user", "content": "hi"}], options={"temperature": 0.05})
    return client.chat.completions.create.call_args.kwargs


def test_reasoning_settings_are_sent_with_every_chat_request():
    sent = _sent(
        _openai_model(
            model="Qwen/Qwen3.8-27B",
            reasoning_effort="medium",
            extra_body=QWEN_THINKING,
            supports_temperature=False,
        )
    )
    assert sent["reasoning_effort"] == "medium"
    assert sent["extra_body"] == QWEN_THINKING
    assert "temperature" not in sent


def test_defaults_keep_previous_request_shape():
    sent = _sent(_openai_model(model="openai/gpt-oss-120b"))
    assert sent["temperature"] == 0.05
    assert "reasoning_effort" not in sent
    assert "extra_body" not in sent


def test_gpt5_models_still_drop_temperature_without_explicit_flag():
    assert "temperature" not in _sent(_openai_model(model="gpt-5-mini"))


def test_langchain_client_carries_reasoning_settings():
    model, _ = _openai_model(
        model="Qwen/Qwen3.8-27B", reasoning_effort="medium", extra_body=QWEN_THINKING
    )
    client = model.langchain_client()
    assert client.reasoning_effort == "medium"
    assert client.extra_body == QWEN_THINKING


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("gpt-oss:120b", "high"),
        ("qwen3.8:27b", True),
        ("gemma3:27b", None),
    ],
)
def test_ollama_think_defaults_by_family(model, expected):
    assert OllamaLanguageModel(model, host="http://ollama.example")._think == expected


def test_ollama_explicit_think_overrides_family_default():
    model = OllamaLanguageModel(
        "gpt-oss:120b", host="http://ollama.example", think="low"
    )
    assert model._think == "low"
    assert model.langchain_client().reasoning == "low"
