import os
from unittest.mock import MagicMock, patch

import httpx
import pytest
from openai import BadRequestError, OpenAI
from pydantic import ValidationError

import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.llm.external.openai_chat import (
    AzureOpenAIChatModel,
    DirectOpenAIChatModel,
)


def _azure_model(**overrides) -> dict:
    config = {
        "id": "azure-test",
        "type": "azure_chat",
        "model": "gpt-test",
        "api_version": "2025-04-01-preview",
        "azure_deployment": "gpt-test",
        "endpoint": "https://example.openai.azure.com",
    }
    config.update(overrides)
    return config


def test_direct_openai_resolves_api_key_from_environment():
    with (
        patch.dict(
            os.environ, {"TEST_OPENAI_KEY": "sk-test"}
        ),  # pragma: allowlist secret
        patch("iris.llm.external.openai_chat.OpenAI") as client,
    ):
        DirectOpenAIChatModel(
            id="direct-test",
            type="openai_chat",
            model="gpt-test",
            api_key_env="TEST_OPENAI_KEY",  # pragma: allowlist secret
        )

    assert client.call_args.kwargs["api_key"] == "sk-test"  # pragma: allowlist secret


def test_missing_api_key_environment_variable_fails_closed():
    with (
        patch.dict(os.environ, {}, clear=True),
        pytest.raises(ValidationError, match="No API key found"),
    ):
        AzureOpenAIChatModel(
            **_azure_model(api_key_env="MISSING_OPENAI_KEY")  # pragma: allowlist secret
        )


def test_azure_ad_chat_completions_uses_refreshing_token_provider():
    token_provider = MagicMock(name="token_provider")
    with (
        patch.object(
            AzureOpenAIChatModel,
            "_azure_ad_token_provider",
            return_value=token_provider,
        ),
        patch("iris.llm.external.openai_chat.AzureOpenAI") as client,
    ):
        AzureOpenAIChatModel(**_azure_model(auth_mode="azure_ad"))

    assert client.call_args.kwargs["azure_ad_token_provider"] is token_provider
    assert "api_key" not in client.call_args.kwargs


def test_azure_ad_responses_uses_refreshing_token_provider():
    token_provider = MagicMock(name="token_provider")
    with (
        patch.object(
            AzureOpenAIChatModel,
            "_azure_ad_token_provider",
            return_value=token_provider,
        ),
        patch("iris.llm.external.openai_chat.OpenAI") as client,
    ):
        AzureOpenAIChatModel(
            **_azure_model(auth_mode="azure_ad", use_responses_api=True)
        )

    assert client.call_args.kwargs["api_key"] is token_provider
    assert client.call_args.kwargs["base_url"].endswith("/openai/v1/")
    assert "default_headers" not in client.call_args.kwargs


def test_openai_sdk_refreshes_callable_bearer_token_for_each_responses_request():
    tokens = iter(("entra-token-one", "entra-token-two"))
    authorization_headers: list[str] = []

    def token_provider() -> str:
        return next(tokens)

    def reject_after_recording(request: httpx.Request) -> httpx.Response:
        authorization_headers.append(request.headers["authorization"])
        return httpx.Response(
            400,
            json={"error": {"message": "stop after auth capture", "type": "test"}},
        )

    transport = httpx.MockTransport(reject_after_recording)
    with httpx.Client(transport=transport) as http_client:
        client = OpenAI(
            api_key=token_provider,
            base_url="https://example.openai.azure.com/openai/v1/",
            http_client=http_client,
            max_retries=0,
        )
        for _ in range(2):
            with pytest.raises(BadRequestError):
                client.responses.create(model="gpt-test", input="hello")

    assert authorization_headers == [
        "Bearer entra-token-one",
        "Bearer entra-token-two",
    ]


def test_azure_ad_rejects_api_key_configuration():
    with pytest.raises(
        ValidationError,
        match="must not be combined with an API key",
    ):
        AzureOpenAIChatModel(
            **_azure_model(
                auth_mode="azure_ad",
                api_key="sk-test",  # pragma: allowlist secret
            )
        )


def test_azure_api_key_responses_preserves_api_key_header():
    with patch("iris.llm.external.openai_chat.OpenAI") as client:
        AzureOpenAIChatModel(
            **_azure_model(
                api_key="sk-test",  # pragma: allowlist secret
                use_responses_api=True,
            )
        )

    assert client.call_args.kwargs["default_headers"] == {
        "api-key": "sk-test"  # pragma: allowlist secret
    }
