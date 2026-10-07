# pylint: disable=protected-access
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from memiris.llm.ollama_language_model import OllamaLanguageModel
from memiris.llm.openai_language_model import OpenAiLanguageModel


def _openai_model(model: str, **kwargs) -> OpenAiLanguageModel:
    return OpenAiLanguageModel(
        model=model,
        api_key="sk-test",  # pragma: allowlist secret
        base_url="https://logos.example/v1",
        **kwargs,
    )


def _sent(model: OpenAiLanguageModel) -> dict:
    """Run a chat with a temperature set and return the request kwargs."""
    client = MagicMock()
    client.chat.completions.create.return_value = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(role="assistant", content="[]", tool_calls=None)
            )
        ],
        model=model.model,
    )
    model._client = client
    model.chat([{"role": "user", "content": "hi"}], options={"temperature": 0.05})
    return client.chat.completions.create.call_args.kwargs


def test_explicit_supports_temperature_false_drops_temperature():
    # A reasoning model such as o3 has no gpt-5 name prefix but rejects
    # temperature; the explicit Iris flag must override the name-based default.
    assert "temperature" not in _sent(_openai_model("o3", supports_temperature=False))


def test_explicit_supports_temperature_true_sends_temperature():
    assert _sent(_openai_model("o3", supports_temperature=True))["temperature"] == 0.05


def test_gpt5_name_default_still_drops_temperature():
    # No explicit flag: the name-based default keeps GPT-5 models from sending
    # a parameter their endpoint rejects.
    assert "temperature" not in _sent(_openai_model("gpt-5-mini"))


def test_non_gpt5_name_default_sends_temperature():
    # No explicit flag on a non-gpt-5 model keeps the previous behaviour.
    assert _sent(_openai_model("openai/gpt-oss-120b"))["temperature"] == 0.05


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("gpt-oss:120b", "high"),
        ("qwen3.8:27b", True),
        ("qwen3.6:35b-a3b", True),
        ("qwen3-coder:30b", None),
        ("qwen3.5-coder:32b", None),
        ("qwen3-embedding:8b", None),
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


def test_ollama_direct_chat_uses_configured_think():
    # The direct (non-LangChain) client must honour the same setting.
    model = OllamaLanguageModel(
        "gpt-oss:120b", host="http://ollama.example", think="low"
    )
    model._client = MagicMock()
    model._langfuse = MagicMock()
    model.chat([{"role": "user", "content": "hi"}])
    assert model._client.chat.call_args.kwargs["think"] == "low"
