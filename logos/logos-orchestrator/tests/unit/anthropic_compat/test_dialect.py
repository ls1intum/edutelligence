"""Which upstreams get an Anthropic Messages request forwarded verbatim.

The whole translation only exists for upstreams without a Messages route.
Classifying one of those as native puts the
request back on the 404 path, and classifying a native one as OpenAI-shaped
costs fidelity on every turn, so the decision is pinned here.
"""

from logos.anthropic_compat import (
    CHAT_COMPLETIONS_PATH,
    MESSAGES_PATH,
    UpstreamDialect,
    dialect_for,
    forward_path_for,
    is_messages_path,
    stream_translator,
    translate_error,
    translate_request,
    translate_response,
)

AZURE_CHAT = (
    "https://ase-se01.openai.azure.com/openai/deployments/gpt-41-mini/chat/completions?api-version=2025-01-01-preview"
)
AZURE_RESPONSES = "https://ase-se01.openai.azure.com/openai/responses?api-version=2025-04-01-preview"


def test_workernode_serves_messages_natively():
    # vLLM answers POST /v1/messages itself, which is why claude-logos works
    # against a workernode with no translation at all.
    assert dialect_for(provider_type="logosnode", cloud_provider_type=None) is UpstreamDialect.NATIVE


def test_logos_upstream_serves_messages_natively():
    # A Logos instance upstream serves every surface this one does.
    assert (
        dialect_for(provider_type="cloud", cloud_provider_type="logos", forward_url="https://logos.test/v1/messages")
        is UpstreamDialect.NATIVE
    )


def test_anthropic_cloud_upstream_serves_messages_natively():
    assert dialect_for(provider_type="cloud", cloud_provider_type="anthropic") is UpstreamDialect.NATIVE


def test_azure_chat_deployment_uses_chat_completions():
    assert (
        dialect_for(provider_type="cloud", cloud_provider_type="azure", forward_url=AZURE_CHAT)
        is UpstreamDialect.CHAT_COMPLETIONS
    )


def test_azure_responses_deployment_uses_the_responses_api():
    # A gpt-5.x deployment is stored against /responses and serves no
    # chat/completions route to fall back to.
    assert (
        dialect_for(provider_type="cloud", cloud_provider_type="azure", forward_url=AZURE_RESPONSES)
        is UpstreamDialect.RESPONSES
    )


def test_unset_cloud_type_defaults_to_chat_completions():
    # Providers saved before the type existed have it NULL; chat/completions is
    # the surface an OpenAI-shaped upstream always has.
    assert (
        dialect_for(provider_type="cloud", cloud_provider_type=None, forward_url="https://api.openai.com/v1/messages")
        is UpstreamDialect.CHAT_COMPLETIONS
    )


def test_query_string_does_not_hide_the_responses_route():
    assert (
        dialect_for(provider_type="cloud", cloud_provider_type="openai", forward_url="https://x/v1/responses/")
        is UpstreamDialect.RESPONSES
    )


def test_messages_path_recognised_with_and_without_prefix():
    assert is_messages_path("v1/messages")
    assert is_messages_path("/v1/messages")
    assert is_messages_path("v1/messages?beta=true")  # what Claude Code sends
    assert not is_messages_path("v1/chat/completions")
    assert not is_messages_path(None)


def test_forward_path_follows_the_dialect():
    assert forward_path_for(UpstreamDialect.NATIVE) == MESSAGES_PATH
    assert forward_path_for(UpstreamDialect.CHAT_COMPLETIONS) == CHAT_COMPLETIONS_PATH
    assert forward_path_for(UpstreamDialect.RESPONSES) == CHAT_COMPLETIONS_PATH


def test_native_dialect_translates_nothing():
    payload = {"model": "m", "max_tokens": 8, "messages": [{"role": "user", "content": "hi"}]}
    assert translate_request(payload, UpstreamDialect.NATIVE) is payload
    body = {"type": "message", "content": []}
    assert translate_response(body, UpstreamDialect.NATIVE) is body
    assert stream_translator(UpstreamDialect.NATIVE) is None


def test_error_bodies_become_anthropic_errors():
    # Logos normalises upstream failures to the OpenAI shape before they reach
    # the translation, so the message and type have to survive it.
    assert translate_error({"error": {"message": "too long", "type": "invalid_request_error"}}) == {
        "type": "error",
        "error": {"type": "invalid_request_error", "message": "too long"},
    }
    assert translate_error({"error": "boom"})["error"]["message"] == "boom"
    # An already-Anthropic body is left alone rather than nested twice.
    already = {"type": "error", "error": {"type": "api_error", "message": "x"}}
    assert translate_error(already) is already
