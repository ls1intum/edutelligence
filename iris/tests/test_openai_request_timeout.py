"""Each OpenAI model entry can set its own client timeout."""

import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.llm.external.openai_chat import (  # noqa: E402
    REQUEST_TIMEOUT_SECONDS,
    AzureOpenAIChatModel,
    DirectOpenAIChatModel,
)


def _direct(**fields):
    return DirectOpenAIChatModel(
        id="luna",
        type="openai_chat",
        model="gpt-6-luna",
        api_key="sk-test",  # pragma: allowlist secret
        **fields,
    )


def _azure(**fields):
    return AzureOpenAIChatModel(
        id="azure",
        type="azure_chat",
        model="gpt-5-mini",
        api_key="az-test",  # pragma: allowlist secret
        endpoint="https://example.openai.azure.com",
        azure_deployment="gpt-5-mini",
        api_version="2025-04-01-preview",
        **fields,
    )


def test_the_default_timeout_is_unchanged():
    assert _direct().get_client().timeout == REQUEST_TIMEOUT_SECONDS == 300.0


def test_a_model_entry_sets_its_own_timeout():
    assert _direct(request_timeout_seconds=90).get_client().timeout == 90
    assert (
        _direct(request_timeout_seconds=90, base_url="http://gateway/v1")
        .get_client()
        .timeout
        == 90
    )
    assert _azure(request_timeout_seconds=45).get_client().timeout == 45
    assert (
        _azure(request_timeout_seconds=45, use_responses_api=True).get_client().timeout
        == 45
    )
