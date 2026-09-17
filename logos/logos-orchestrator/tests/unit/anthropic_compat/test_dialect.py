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
    is_chat_completions_path,
    is_messages_path,
    serves_only_messages,
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


def test_a_pinned_chat_endpoint_wins_over_a_native_provider_type():
    """The URL decides: it is the surface the request is actually posted to.

    An operator can pin a per-model endpoint by hand and the model sync
    preserves one, so a Logos provider — which does serve the Messages API —
    can still end up addressed at chat/completions. Trusting the provider type
    there forwards the Anthropic body unchanged and the upstream rejects it.
    """
    assert (
        dialect_for(
            provider_type="cloud",
            cloud_provider_type="logos",
            forward_url="https://logos.aet.cit.tum.de/v1/chat/completions",
        )
        is UpstreamDialect.CHAT_COMPLETIONS
    )
    assert (
        dialect_for(
            provider_type="cloud",
            cloud_provider_type="anthropic",
            forward_url="https://gateway.test/v1/responses",
        )
        is UpstreamDialect.RESPONSES
    )


def test_a_native_provider_keeps_the_messages_route():
    # Nothing changes when the URL names no OpenAI surface.
    assert (
        dialect_for(provider_type="cloud", cloud_provider_type="logos", forward_url="https://logos.test/v1/messages")
        is UpstreamDialect.NATIVE
    )
    assert (
        dialect_for(provider_type="logosnode", cloud_provider_type=None, forward_url="logosnode://provider/4/lane/a")
        is UpstreamDialect.NATIVE
    )


# ── the mirror question: which upstream has no chat/completions route ───────


def test_chat_completions_path_recognised_on_both_api_versions():
    assert is_chat_completions_path("v1/chat/completions")
    assert is_chat_completions_path("/v2/chat/completions")
    assert is_chat_completions_path("v1/chat/completions?x=1")
    assert not is_chat_completions_path("v1/messages")
    assert not is_chat_completions_path(None)


def test_an_anthropic_resource_serves_nothing_but_messages():
    # Foundry answers every OpenAI path on a Claude deployment with
    # api_not_supported, so a chat/completions request has to be translated.
    assert serves_only_messages(provider_type="cloud", cloud_provider_type="anthropic")
    assert serves_only_messages(
        provider_type="cloud",
        cloud_provider_type="azure",
        forward_url="https://ase-se01.openai.azure.com/anthropic/v1/messages",
    )


def test_upstreams_that_serve_both_surfaces_are_not_messages_only():
    """Not the negation of ``dialect_for``: NATIVE does not imply Messages-only.

    vLLM and a Logos instance both answer /v1/messages *and*
    /v1/chat/completions, so a chat request to either needs no translation —
    even though a Messages request to either is forwarded verbatim as NATIVE.
    """
    assert dialect_for(provider_type="logosnode", cloud_provider_type=None) is UpstreamDialect.NATIVE
    assert not serves_only_messages(provider_type="logosnode", cloud_provider_type=None)

    assert (
        dialect_for(provider_type="cloud", cloud_provider_type="logos", forward_url="https://logos.test/v1/messages")
        is UpstreamDialect.NATIVE
    )
    assert not serves_only_messages(provider_type="cloud", cloud_provider_type="logos")


def test_an_openai_shaped_upstream_is_never_messages_only():
    assert not serves_only_messages(provider_type="cloud", cloud_provider_type="openai")
    assert not serves_only_messages(provider_type="cloud", cloud_provider_type="azure", forward_url=AZURE_CHAT)
    assert not serves_only_messages(provider_type="cloud", cloud_provider_type="azure", forward_url=AZURE_RESPONSES)


def test_a_pinned_url_outranks_the_provider_type_here_too():
    # Same rule as dialect_for: the URL is where the request is actually
    # posted, and an operator can pin a per-model endpoint by hand.
    assert not serves_only_messages(
        provider_type="cloud",
        cloud_provider_type="anthropic",
        forward_url="https://gateway.test/v1/chat/completions",
    )
    assert serves_only_messages(
        provider_type="cloud",
        cloud_provider_type="openai",
        forward_url="https://gateway.test/v1/messages",
    )
