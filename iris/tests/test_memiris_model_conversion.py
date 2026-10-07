# pylint: disable=protected-access
from unittest.mock import MagicMock, patch

# Bootstrap the iris package: importing iris.llm directly hits a pre-existing
# circular import between iris.common.pyris_message and iris.domain. Loading
# iris.pipeline.pipeline first establishes the right module init order.
import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.common import memiris_setup  # noqa: E402
from iris.llm import OllamaModel  # noqa: E402
from iris.llm.external.openai_chat import (  # noqa: E402
    AzureOpenAIChatModel,
    DirectOpenAIChatModel,
)


def _convert(model):
    manager = MagicMock()
    manager.get_llm_by_id.return_value = model
    with patch.object(memiris_setup, "LlmManager", return_value=manager):
        return memiris_setup._convert_iris_model_to_memiris_llm(model.id)


def test_openai_supports_temperature_false_reaches_memiris():
    # A reasoning model such as o3 has no gpt-5 name prefix; the explicit flag
    # must override Memiris's name-based default so its endpoint is not sent a
    # parameter it rejects.
    converted = _convert(
        DirectOpenAIChatModel(
            id="o3",
            type="openai_chat",
            model="o3",
            api_key="sk-test",  # pragma: allowlist secret
            base_url="https://logos.example/v1",
            supports_temperature=False,
        )
    )
    assert converted._supports_temperature is False


def test_openai_supports_temperature_true_reaches_memiris():
    converted = _convert(
        DirectOpenAIChatModel(
            id="o3-temps",
            type="openai_chat",
            model="o3",
            api_key="sk-test",  # pragma: allowlist secret
            base_url="https://logos.example/v1",
            supports_temperature=True,
        )
    )
    assert converted._supports_temperature is True


def test_entry_without_temperature_flag_keeps_memiris_name_default():
    # No explicit flag: forward None so Memiris falls back to its own
    # name-based default (gpt-5* reject temperature, everything else accepts).
    assert (
        _convert(
            DirectOpenAIChatModel(
                id="gpt-5-mini",
                type="openai_chat",
                model="gpt-5-mini",
                api_key="sk-test",  # pragma: allowlist secret
            )
        )._supports_temperature
        is False
    )
    assert (
        _convert(
            DirectOpenAIChatModel(
                id="o3-default",
                type="openai_chat",
                model="o3",
                api_key="sk-test",  # pragma: allowlist secret
            )
        )._supports_temperature
        is True
    )


def test_responses_api_model_forwards_explicit_supports_temperature():
    converted = _convert(
        AzureOpenAIChatModel(
            id="gpt-5.5",
            type="azure_chat",
            model="gpt-5.5",
            api_key="sk-test",  # pragma: allowlist secret
            endpoint="https://example.openai.azure.com/",
            azure_deployment="gpt-5.5",
            api_version="2025-04-01-preview",
            supports_temperature=False,
            use_responses_api=True,
        )
    )
    assert converted._supports_temperature is False


def test_ollama_think_setting_reaches_memiris():
    converted = _convert(
        OllamaModel(
            id="gpt-oss-ollama",
            type="ollama",
            model="gpt-oss:120b",
            host="http://ollama.example",
            think="low",
        )
    )
    assert converted._think == "low"


def test_ollama_without_think_uses_family_default():
    converted = _convert(
        OllamaModel(
            id="gpt-oss-default",
            type="ollama",
            model="gpt-oss:120b",
            host="http://ollama.example",
        )
    )
    # gpt-oss only accepts effort levels; the family default is "high".
    assert converted._think == "high"
