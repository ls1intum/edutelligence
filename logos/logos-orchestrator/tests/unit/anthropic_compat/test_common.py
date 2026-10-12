"""Shared anthropic_compat helpers.

``strip_billing_header_from_payload`` is covered here rather than only via
``to_chat_completions``/``to_responses``: it must also run for a request whose
upstream is Messages-native (a vLLM lane, another Logos instance) and is
therefore forwarded verbatim — see the call site in
``pipeline.context_resolver.ContextResolver.prepare_headers_and_payload``.
"""

import pytest

from logos.anthropic_compat.common import (
    strip_billing_header,
    strip_billing_header_from_payload,
    wants_max_completion_tokens,
)

_MARKER = "x-anthropic-billing-header: cc_version=2.1.276.791; cc_entrypoint=cli; "
_PROMPT = "You are Claude Code, Anthropic's official CLI for Claude."


def test_strip_billing_header_drops_a_leading_marker():
    assert strip_billing_header(_MARKER + _PROMPT) == _PROMPT


def test_strip_billing_header_handles_every_observed_variant():
    # cc_workload and cc_is_subagent are present or absent depending on how
    # Claude Code was invoked (interactive, cron, a spawned subagent) — every
    # combination must collapse to the same bytes for the cache to see a hit.
    variants = [
        "x-anthropic-billing-header: cc_version=2.1.226.be8; cc_entrypoint=cli; ",
        "x-anthropic-billing-header: cc_version=2.1.276.9a3; cc_entrypoint=cli; cc_is_subagent=true; ",
        "x-anthropic-billing-header: cc_version=2.1.226.be8; cc_entrypoint=cli; cc_workload=cron; ",
    ]
    stripped = {strip_billing_header(marker + _PROMPT) for marker in variants}
    assert stripped == {_PROMPT}


def test_strip_billing_header_is_a_noop_without_the_marker():
    # Every client that is not Claude Code, and every non-leading occurrence.
    assert strip_billing_header(_PROMPT) == _PROMPT
    embedded = "Please summarise: " + _MARKER + "not actually a marker here"
    assert strip_billing_header(embedded) == embedded


def test_strip_billing_header_from_payload_handles_a_plain_string_system():
    payload = {"system": _MARKER + _PROMPT, "messages": []}
    result = strip_billing_header_from_payload(payload)
    assert result["system"] == _PROMPT
    assert result["messages"] == []


def test_strip_billing_header_from_payload_handles_claude_codes_block_list_shape():
    # Claude Code sends system as a list of text blocks, one per section, the
    # first one optionally carrying a prompt-caching cache_control entry that
    # must survive untouched.
    payload = {
        "system": [
            {"type": "text", "text": _MARKER + _PROMPT, "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": "Be brief."},
        ],
    }
    result = strip_billing_header_from_payload(payload)
    assert result["system"] == [
        {"type": "text", "text": _PROMPT, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "Be brief."},
    ]


def test_strip_billing_header_from_payload_returns_the_same_object_without_a_marker():
    # No system field, and a system that does not start with the marker, are
    # both the common case for every client that is not Claude Code -- this
    # must stay a cheap no-op, not a defensive copy on every request.
    no_system = {"messages": [{"role": "user", "content": "hi"}]}
    assert strip_billing_header_from_payload(no_system) is no_system

    clean = {"system": _PROMPT, "messages": []}
    assert strip_billing_header_from_payload(clean) is clean


def test_strip_billing_header_preserves_newlines_after_the_marker():
    # The marker's own trailing whitespace must not eat formatting the prompt
    # put there on purpose -- a blank line separating the marker from the
    # actual system prompt has to survive the strip.
    assert strip_billing_header(_MARKER + "\n\n" + _PROMPT) == "\n\n" + _PROMPT
    assert strip_billing_header(_MARKER + "\n" + _PROMPT) == "\n" + _PROMPT


def test_strip_billing_header_from_payload_drops_a_marker_only_string_system():
    # Stripping a system prompt that is *nothing but* the marker would
    # otherwise forward an empty string; drop the field instead.
    payload = {"system": _MARKER, "messages": []}
    result = strip_billing_header_from_payload(payload)
    assert "system" not in result
    assert result["messages"] == []


def test_strip_billing_header_from_payload_drops_a_marker_only_first_block_with_more_blocks():
    # The Messages API rejects an empty text block outright, so a marker-only
    # first block must be dropped entirely rather than forwarded as
    # {"type": "text", "text": ""} -- the later blocks still carry real
    # instructions and must survive.
    payload = {
        "system": [
            {"type": "text", "text": _MARKER},
            {"type": "text", "text": "Be brief."},
        ],
    }
    result = strip_billing_header_from_payload(payload)
    assert result["system"] == [{"type": "text", "text": "Be brief."}]


def test_strip_billing_header_from_payload_drops_system_when_the_only_block_is_marker_only():
    payload = {"system": [{"type": "text", "text": _MARKER}], "messages": []}
    result = strip_billing_header_from_payload(payload)
    assert "system" not in result
    assert result["messages"] == []


def test_strip_billing_header_from_payload_preserves_everything_else():
    payload = {
        "model": "Qwen/Qwen3.8-27B",
        "system": _MARKER + _PROMPT,
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 200,
        "stream": True,
    }
    result = strip_billing_header_from_payload(payload)
    assert result["model"] == "Qwen/Qwen3.8-27B"
    assert result["messages"] == [{"role": "user", "content": "hi"}]
    assert result["max_tokens"] == 200
    assert result["stream"] is True


@pytest.mark.parametrize(
    "endpoint_url,expected",
    [
        ("https://api.openai.com/v1/chat/completions", True),
        (
            "https://ase.openai.azure.com/openai/deployments/gpt-6-luna/chat/completions"
            "?api-version=2025-01-01-preview",
            True,
        ),
        ("https://api.openai.com/v1/completions", False),
        ("https://api.openai.com/v1/completions?foo=1", False),
        # Azure api-versions before 2024-09-01 predate max_completion_tokens.
        ("https://x.openai.azure.com/openai/deployments/turbo/chat/completions?api-version=2024-02-01", False),
        ("https://x.openai.azure.com/openai/deployments/turbo/chat/completions?api-version=2024-08-01-preview", False),
        ("https://x.openai.azure.com/openai/deployments/m/chat/completions?api-version=2024-09-01-preview", True),
        ("https://x.openai.azure.com/openai/deployments/m/chat/completions?api-version=2025-01-01-preview", True),
        (None, True),
        ("", True),
    ],
)
def test_wants_max_completion_tokens_follows_the_endpoint_path(endpoint_url, expected):
    assert wants_max_completion_tokens(endpoint_url) is expected
