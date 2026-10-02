# pylint: disable=protected-access
from unittest.mock import MagicMock, patch

import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.common import memiris_setup  # noqa: E402
from iris.llm import OllamaModel  # noqa: E402
from iris.llm.external.openai_chat import DirectOpenAIChatModel  # noqa: E402
from iris.pipeline.shared.confidence_scoring import is_large_model  # noqa: E402

QWEN_THINKING = {"chat_template_kwargs": {"enable_thinking": True}}


def _convert(model):
    manager = MagicMock()
    manager.get_llm_by_id.return_value = model
    with patch.object(memiris_setup, "LlmManager", return_value=manager):
        return memiris_setup._convert_iris_model_to_memiris_llm(model.id)


def test_openai_chat_request_settings_reach_memiris():
    converted = _convert(
        DirectOpenAIChatModel(
            id="Qwen/Qwen3.8-27B",
            type="openai_chat",
            model="Qwen/Qwen3.8-27B",
            api_key="sk-test",  # pragma: allowlist secret
            base_url="https://logos.example/v1",
            supports_temperature=False,
            supports_reasoning_effort=True,
            reasoning_effort="medium",
            reasoning_effort_values=["low", "medium", "xhigh"],
            extra_body=QWEN_THINKING,
        )
    )
    assert converted._reasoning_effort == "medium"
    assert converted._extra_body == QWEN_THINKING
    assert converted._supports_temperature is False


def test_gpt_oss_entry_without_extra_body_keeps_its_effort():
    converted = _convert(
        DirectOpenAIChatModel(
            id="openai/gpt-oss-120b",
            type="openai_chat",
            model="openai/gpt-oss-120b",
            api_key="sk-test",  # pragma: allowlist secret
            base_url="https://logos.example/v1",
            supports_reasoning_effort=True,
            reasoning_effort="medium",
        )
    )
    assert converted._reasoning_effort == "medium"
    assert converted._extra_body is None
    assert converted._supports_temperature is True


def test_ollama_think_setting_reaches_memiris():
    converted = _convert(
        OllamaModel(
            id="qwen-ollama",
            type="ollama",
            model="qwen3.8:27b",
            host="http://ollama.example",
            think=False,
        )
    )
    assert converted._think is False


def test_qwen38_uses_the_large_model_confidence_prompt():
    assert is_large_model("Qwen/Qwen3.8-27B")
    assert is_large_model("openai/gpt-oss-120b")
    assert not is_large_model("google/gemma-3-12b-it")
