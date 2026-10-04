"""The billing-header strip must run on the NATIVE/verbatim forward too.

``anthropic_compat.common.system_and_messages`` only runs inside
``to_chat_completions``/``to_responses`` — the translations for a
cloud upstream that does not speak the Messages API. A workernode (vLLM) and
another Logos instance both serve the Messages API themselves, so
``translate_request`` returns the payload unchanged for
``UpstreamDialect.NATIVE`` (see ``anthropic_compat/__init__.py``), and the
translations above never run. This is exactly the path Claude Code's traffic
to a local vLLM lane takes, so the strip has to happen in
``prepare_headers_and_payload`` itself, before that branch.
"""

from logos.anthropic_compat import UpstreamDialect
from logos.pipeline.context_resolver import ContextResolver, ExecutionContext

_MARKER = "x-anthropic-billing-header: cc_version=2.1.276.791; cc_entrypoint=cli; "
_PROMPT = "You are Claude Code, Anthropic's official CLI for Claude."


def _context(**overrides) -> ExecutionContext:
    base = dict(
        model_id=1,
        provider_id=7,
        provider_name="deimama",
        provider_type="logosnode",
        forward_url="ws://deimama/v1/messages",
        auth_header="",
        auth_value="",
        model_name="Qwen/Qwen3.8-27B",
    )
    base.update(overrides)
    return ExecutionContext(**base)


def test_native_logosnode_forward_still_strips_the_marker():
    # anthropic_dialect is None here on purpose: a logosnode provider is
    # classified NATIVE by dialect_for(), and prepare_headers_and_payload
    # only calls translate_request when anthropic_dialect is not None -- the
    # strip must not depend on that branch being taken.
    context = _context(anthropic_dialect=None)
    payload = {"model": "Qwen/Qwen3.8-27B", "system": _MARKER + _PROMPT, "messages": []}

    _, prepared = ContextResolver.prepare_headers_and_payload(context, payload)

    assert prepared["system"] == _PROMPT


def test_explicit_native_dialect_forward_still_strips_the_marker():
    # A workernode reached through the Anthropic-native route can also carry
    # anthropic_dialect=NATIVE explicitly; translate_request is a no-op for
    # it (returns payload unchanged), so this must not silently undo the strip.
    context = _context(anthropic_dialect=UpstreamDialect.NATIVE)
    payload = {"model": "Qwen/Qwen3.8-27B", "system": _MARKER + _PROMPT, "messages": []}

    _, prepared = ContextResolver.prepare_headers_and_payload(context, payload)

    assert prepared["system"] == _PROMPT


def test_chat_completions_dialect_forward_also_strips_the_marker():
    # The cloud-upstream translation path: the marker must not survive into
    # the hoisted system message either.
    context = _context(
        provider_type="cloud",
        anthropic_dialect=UpstreamDialect.CHAT_COMPLETIONS,
        forward_url="https://example.azure.com/openai/deployments/gpt/chat/completions",
    )
    payload = {"model": "gpt-4o", "system": _MARKER + _PROMPT, "messages": []}

    _, prepared = ContextResolver.prepare_headers_and_payload(context, payload)

    assert prepared["messages"][0] == {"role": "system", "content": _PROMPT}
