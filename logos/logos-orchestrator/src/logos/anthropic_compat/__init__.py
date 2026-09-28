# src/logos/anthropic_compat/__init__.py
"""Make the Messages API and chat/completions reachable on either upstream.

Logos serves both surfaces, and an upstream rarely serves both. Which
translation a request needs therefore follows from two things: the API the
client addressed, and the API the resolved upstream speaks.

``POST /v1/messages`` is what Claude Code (and every Anthropic SDK) talks to.
vLLM serves that surface itself, and so does another Logos instance, so those
requests are forwarded verbatim. An Azure or OpenAI resource does not: it has
``chat/completions`` and ``responses`` and would answer a forwarded Messages
path with 404.

The reverse happens on a Claude deployment. Azure Foundry serves it on
``/anthropic/v1/messages`` and offers no OpenAI-shaped route at all, so a
``POST /v1/chat/completions`` addressed to one has to travel the other way —
out as a Messages request, back as a chat/completions body.

The entry points are ``dialect_for`` and ``serves_only_messages``, which
classify an upstream from each side, and the ``translate_*`` helpers plus
``stream_translator`` / ``MessagesStreamTranslator``, which the forwarding
layer calls once each per request.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Union

from logos.anthropic_compat.chat_completions import (
    ChatCompletionsStreamTranslator,
    from_chat_completion,
    to_chat_completions,
)
from logos.anthropic_compat.common import (
    CHAT_COMPLETIONS_PATH,
    MESSAGES_PATH,
    UpstreamDialect,
    error_body,
    is_chat_completions_path,
    is_messages_path,
)
from logos.anthropic_compat.messages_api import MessagesStreamTranslator, from_message, to_messages
from logos.anthropic_compat.responses_api import ResponsesStreamTranslator, from_response, to_responses

__all__ = [
    "MESSAGES_PATH",
    "CHAT_COMPLETIONS_PATH",
    "MessagesStreamTranslator",
    "UpstreamDialect",
    "dialect_for",
    "forward_path_for",
    "from_message",
    "is_chat_completions_path",
    "is_messages_path",
    "serves_only_messages",
    "stream_translator",
    "to_messages",
    "translate_error",
    "translate_request",
    "translate_response",
]

# Cloud provider types that serve the Anthropic Messages API themselves.
# "logos" is another Logos instance used as an upstream, which serves every
# surface this one does.
_NATIVE_CLOUD_PROVIDERS = frozenset({"anthropic", "logos"})

StreamTranslator = Union[ChatCompletionsStreamTranslator, ResponsesStreamTranslator]


def dialect_for(
    *,
    provider_type: Optional[str],
    cloud_provider_type: Optional[str],
    forward_url: Optional[str] = None,
) -> UpstreamDialect:
    """Which API surface a resolved upstream serves for a Messages request.

    The resolved URL decides first, because it is the surface the request is
    actually posted to. An operator can pin a per-model endpoint by hand, and
    the model sync deliberately preserves one — so even a provider that serves
    the Messages API can end up addressed at ``chat/completions``, and sending
    an Anthropic body there is a 400. ``.../anthropic/v1/messages`` is the
    native route Azure Foundry serves Claude models on from an otherwise
    OpenAI-shaped host. Only when the URL names neither surface does the
    provider type decide: a workernode runs vLLM, and Anthropic and Logos
    cloud upstreams serve the Messages API themselves, so all three keep the
    verbatim forward.
    """
    path = (forward_url or "").split("?", 1)[0].rstrip("/")
    if path.endswith("/responses"):
        return UpstreamDialect.RESPONSES
    if path.endswith("/chat/completions"):
        return UpstreamDialect.CHAT_COMPLETIONS
    if path.endswith("/anthropic/v1/messages"):
        return UpstreamDialect.NATIVE
    if (provider_type or "").lower() == "logosnode":
        return UpstreamDialect.NATIVE
    if (cloud_provider_type or "").lower() in _NATIVE_CLOUD_PROVIDERS:
        return UpstreamDialect.NATIVE
    return UpstreamDialect.CHAT_COMPLETIONS


def serves_only_messages(
    *,
    provider_type: Optional[str],
    cloud_provider_type: Optional[str],
    forward_url: Optional[str] = None,
) -> bool:
    """Whether this upstream has no chat/completions route to forward to.

    The question :func:`dialect_for` asks from the other side, and it is not
    its negation: an upstream can serve both surfaces. vLLM does, and so does
    a Logos instance used as an upstream — both are ``NATIVE`` for a Messages
    request *and* answer chat/completions directly, so neither needs anything
    translated.

    An Anthropic resource is the one that does not. Azure Foundry publishes
    Claude on ``/anthropic/v1/messages`` and answers every OpenAI path on that
    resource with ``api_not_supported``; the Claude API itself has an OpenAI
    compatibility layer, but Anthropic documents it as a testing aid that
    silently ignores half the request, so the Messages route is the one worth
    addressing either way.

    As in ``dialect_for``, a URL that names a surface outranks the provider
    type — it is where the request is actually posted, and an operator can pin
    a per-model endpoint by hand.
    """
    path = (forward_url or "").split("?", 1)[0].rstrip("/")
    if path.endswith("/chat/completions") or path.endswith("/responses"):
        return False
    if path.endswith("/messages"):
        return True
    if (provider_type or "").lower() == "logosnode":
        return False
    return (cloud_provider_type or "").lower() == "anthropic"


def forward_path_for(dialect: UpstreamDialect) -> str:
    """The inbound path to forward under, for a given upstream dialect."""
    return MESSAGES_PATH if dialect is UpstreamDialect.NATIVE else CHAT_COMPLETIONS_PATH


def translate_request(
    payload: Dict[str, Any],
    dialect: UpstreamDialect,
    *,
    model_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Rewrite a Messages request body for the upstream's dialect."""
    if dialect is UpstreamDialect.CHAT_COMPLETIONS:
        return to_chat_completions(payload, model_name=model_name)
    if dialect is UpstreamDialect.RESPONSES:
        return to_responses(payload)
    return payload


def translate_response(
    body: Any,
    dialect: UpstreamDialect,
    *,
    model_name: Optional[str] = None,
) -> Any:
    """Rewrite an upstream response body into an Anthropic message."""
    if not isinstance(body, dict):
        return body
    if dialect is UpstreamDialect.CHAT_COMPLETIONS:
        return from_chat_completion(body, model_name=model_name)
    if dialect is UpstreamDialect.RESPONSES:
        return from_response(body, model_name=model_name)
    return body


def translate_error(body: Any) -> Dict[str, Any]:
    """Rewrite an upstream error body into the Anthropic error shape.

    Logos normalises upstream failures to the OpenAI shape
    (``{"error": {"message": ..., "type": ...}}``) before they reach here, so
    the message and type usually survive; anything else is stringified rather
    than dropped.
    """
    if isinstance(body, dict) and body.get("type") == "error" and isinstance(body.get("error"), dict):
        return body
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, dict):
        return error_body(str(error.get("message") or error), str(error.get("type") or "api_error"))
    if error is not None:
        return error_body(str(error))
    return error_body(str(body) if body else "upstream request failed")


def stream_translator(
    dialect: UpstreamDialect,
    *,
    model_name: Optional[str] = None,
) -> Optional[StreamTranslator]:
    """A stream translator for the dialect, or ``None`` for native upstreams."""
    if dialect is UpstreamDialect.CHAT_COMPLETIONS:
        return ChatCompletionsStreamTranslator(model_name)
    if dialect is UpstreamDialect.RESPONSES:
        return ResponsesStreamTranslator(model_name)
    return None
