"""Where POST /v1/messages is forwarded, and in which shape.

The failure this pins down: a Messages request was forwarded like-for-like to
every cloud upstream, so an Azure or OpenAI resource — which has no
``/v1/messages`` route — answered 404 before the model saw anything.
"""

from contextlib import contextmanager
from typing import Any, Dict, Optional

import pytest

from logos.anthropic_compat import UpstreamDialect
from logos.pipeline import context_resolver as cr_module
from logos.pipeline.context_resolver import ContextResolver

AZURE_CHAT_ENDPOINT = (
    "https://ase-se01.openai.azure.com/openai/deployments/"
    "gpt-41-mini/chat/completions?api-version=2025-01-01-preview"
)
AZURE_RESPONSES_ENDPOINT = (
    "https://ase-se01.openai.azure.com/openai/deployments/" "gpt-56-luna/responses?api-version=2025-04-01-preview"
)

MESSAGES_BODY = {
    "model": "gpt-4.1-nano",
    "max_tokens": 32,
    "system": "Be brief.",
    "messages": [{"role": "user", "content": "hi"}],
}


@contextmanager
def _patched_db(monkeypatch, auth_info: Optional[Dict[str, Any]]):
    class DummyDB:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def get_auth_info_to_deployment(self, model_id, provider_id):  # noqa: ARG002
            return auth_info

    monkeypatch.setattr(cr_module, "DBManager", DummyDB)
    yield


def _auth_info(**overrides: Any) -> Dict[str, Any]:
    info = {
        "provider_type": "cloud",
        "cloud_provider_type": "openai",
        "provider_name": "Upstream",
        "model_name": "gpt-4.1-nano",
        "endpoint": "",
        "base_url": "https://api.openai.com/v1",
        "api_key": "sk-secret",
        "auth_name": "",
        "auth_format": "",
    }
    info.update(overrides)
    return info


async def _resolve(monkeypatch, path: str, **overrides: Any):
    with _patched_db(monkeypatch, _auth_info(**overrides)):
        return await ContextResolver().resolve_context(35, 4, path)


@pytest.mark.asyncio
async def test_openai_upstream_is_addressed_on_chat_completions(monkeypatch):
    context = await _resolve(monkeypatch, "v1/messages")
    assert context.forward_url == "https://api.openai.com/v1/chat/completions"
    assert context.anthropic_dialect is UpstreamDialect.CHAT_COMPLETIONS


@pytest.mark.asyncio
async def test_logos_upstream_keeps_the_messages_path(monkeypatch):
    # Another Logos instance serves the Messages API itself, so the request is
    # forwarded verbatim and nothing is translated.
    context = await _resolve(
        monkeypatch,
        "v1/messages",
        cloud_provider_type="logos",
        base_url="https://logos.aet.cit.tum.de/v1",
    )
    assert context.forward_url == "https://logos.aet.cit.tum.de/v1/messages"
    assert context.anthropic_dialect is UpstreamDialect.NATIVE


@pytest.mark.asyncio
async def test_azure_chat_deployment_keeps_its_stored_endpoint(monkeypatch):
    # The deployment id and api-version cannot be reconstructed from base_url,
    # so the stored URL wins and only the dialect is derived from it.
    context = await _resolve(
        monkeypatch,
        "v1/messages",
        cloud_provider_type="azure",
        base_url="https://ase-se01.openai.azure.com/openai/deployments/",
        endpoint=AZURE_CHAT_ENDPOINT,
    )
    assert context.forward_url == AZURE_CHAT_ENDPOINT
    assert context.anthropic_dialect is UpstreamDialect.CHAT_COMPLETIONS


@pytest.mark.asyncio
async def test_azure_reasoning_deployment_uses_the_responses_dialect(monkeypatch):
    context = await _resolve(
        monkeypatch,
        "v1/messages",
        cloud_provider_type="azure",
        model_name="gpt-5.6-luna",
        base_url="https://ase-se01.openai.azure.com/openai/deployments/",
        endpoint=AZURE_RESPONSES_ENDPOINT,
    )
    assert context.forward_url == "https://ase-se01.openai.azure.com/openai/responses?api-version=2025-04-01-preview"
    assert context.azure_responses_deployment == "gpt-56-luna"
    assert context.anthropic_dialect is UpstreamDialect.RESPONSES


@pytest.mark.asyncio
async def test_non_messages_routes_are_untouched(monkeypatch):
    context = await _resolve(monkeypatch, "v1/chat/completions")
    assert context.forward_url == "https://api.openai.com/v1/chat/completions"
    assert context.anthropic_dialect is None


@pytest.mark.asyncio
async def test_workernode_request_is_never_translated(monkeypatch):
    class DummyRegistry:
        async def select_lane_for_model(self, provider_id, model_name):  # noqa: ARG002
            return {"lane_id": "lane-1"}

    with _patched_db(monkeypatch, _auth_info(provider_type="logosnode", cloud_provider_type=None, api_key=None)):
        context = await ContextResolver(logosnode_registry=DummyRegistry()).resolve_context(35, 4, "v1/messages")
    assert context.forward_url == "logosnode://provider/4/lane/lane-1"
    assert context.anthropic_dialect is UpstreamDialect.NATIVE


@pytest.mark.asyncio
async def test_payload_is_translated_for_an_openai_upstream(monkeypatch):
    context = await _resolve(monkeypatch, "v1/messages")
    _, payload = ContextResolver.prepare_headers_and_payload(context, MESSAGES_BODY)
    assert payload["messages"][0] == {"role": "system", "content": "Be brief."}
    assert payload["max_tokens"] == 32
    assert "system" not in payload


@pytest.mark.asyncio
async def test_payload_is_left_alone_for_a_logos_upstream(monkeypatch):
    context = await _resolve(monkeypatch, "v1/messages", cloud_provider_type="logos")
    _, payload = ContextResolver.prepare_headers_and_payload(context, MESSAGES_BODY)
    assert payload["system"] == "Be brief."


@pytest.mark.asyncio
async def test_azure_responses_deployment_rewrite_applies_to_the_translated_body(monkeypatch):
    # Azure /responses resolves the deployment from the body's "model", which
    # must survive the Messages -> Responses translation.
    context = await _resolve(
        monkeypatch,
        "v1/messages",
        cloud_provider_type="azure",
        model_name="gpt-5.6-luna",
        base_url="https://ase-se01.openai.azure.com/openai/deployments/",
        endpoint=AZURE_RESPONSES_ENDPOINT,
    )
    _, payload = ContextResolver.prepare_headers_and_payload(context, {**MESSAGES_BODY, "model": "gpt-5.6-luna"})
    assert payload["model"] == "gpt-56-luna"
    assert payload["instructions"] == "Be brief."
    assert payload["max_output_tokens"] == 32
