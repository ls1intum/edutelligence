"""How much context window a request needs — see logos.context_budget."""

from __future__ import annotations

from logos.context_budget import (
    CHARS_PER_TOKEN,
    DEFAULT_OUTPUT_RESERVE_TOKENS,
    SAFETY_MARGIN_TOKENS,
    estimate_prompt_tokens,
    required_context_tokens,
    reserved_output_tokens,
)


class TestEstimatePromptTokens:
    def test_counts_chat_messages(self):
        payload = {"messages": [{"role": "user", "content": "x" * 300}]}
        # Rounds up rather than down: underestimating means a request the worker
        # rejects, overestimating only means a roomier worker. The role name is
        # counted too — it really does reach the model, via the chat template.
        estimate = estimate_prompt_tokens(payload)
        assert estimate >= int(300 / CHARS_PER_TOKEN) + 1
        assert estimate < int(320 / CHARS_PER_TOKEN) + 1

    def test_counts_system_and_tools_too(self):
        """A coding assistant's tool definitions dwarf the conversation.

        Claude Code sends ~60 tool schemas on every turn; ignoring them would
        put the estimate tens of thousands of tokens under the truth.
        """
        without_tools = estimate_prompt_tokens({"messages": [{"role": "user", "content": "hi"}]})
        with_tools = estimate_prompt_tokens(
            {
                "messages": [{"role": "user", "content": "hi"}],
                "system": "y" * 600,
                "tools": [{"name": "Bash", "description": "z" * 900}],
            }
        )
        assert with_tools > without_tools + 400

    def test_reads_responses_api_and_legacy_completions(self):
        assert estimate_prompt_tokens({"input": "a" * 90}) == 31
        assert estimate_prompt_tokens({"prompt": "a" * 90}) == 31
        assert estimate_prompt_tokens({"instructions": "a" * 90}) == 31

    def test_ignores_base64_attachments(self):
        """An encoded image is ~1.4 chars per byte of nothing readable.

        Counting it as prose would push a two-sentence prompt past any window
        and send every image request to the widest worker for no reason.
        """
        text_only = {"messages": [{"role": "user", "content": [{"type": "text", "text": "hello"}]}]}
        with_image = {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "hello"},
                        {"type": "image", "source": {"type": "base64", "data": "A" * 500_000}},
                    ],
                }
            ]
        }
        # The block's own type names are counted (they are a handful of tokens);
        # the half-megabyte of encoded pixels is not.
        assert estimate_prompt_tokens(with_image) - estimate_prompt_tokens(text_only) < 20

    def test_ignores_data_uris_without_a_wrapper_key(self):
        payload = {"messages": [{"role": "user", "content": "data:image/png;base64," + "B" * 100_000}]}
        # Only the surrounding "user" remains: the 100k-character URI is skipped.
        assert estimate_prompt_tokens(payload) < 10

    def test_returns_zero_for_what_it_cannot_read(self):
        assert estimate_prompt_tokens(None) == 0
        assert estimate_prompt_tokens("not a dict") == 0
        assert estimate_prompt_tokens({}) == 0
        assert estimate_prompt_tokens({"model": "some-model", "stream": True}) == 0


class TestReservedOutputTokens:
    def test_uses_the_requested_cap(self):
        assert reserved_output_tokens({"max_tokens": 4096}) == 4096
        assert reserved_output_tokens({"max_completion_tokens": 512}) == 512
        assert reserved_output_tokens({"max_output_tokens": 128}) == 128

    def test_falls_back_when_uncapped(self):
        # An uncapped request can generate until it hits the window, so the
        # fallback has to be the largest reservation any client makes.
        assert reserved_output_tokens({}) == DEFAULT_OUTPUT_RESERVE_TOKENS
        assert reserved_output_tokens({"max_tokens": None}) == DEFAULT_OUTPUT_RESERVE_TOKENS
        assert reserved_output_tokens({"max_tokens": "nonsense"}) == DEFAULT_OUTPUT_RESERVE_TOKENS
        assert reserved_output_tokens({"max_tokens": 0}) == DEFAULT_OUTPUT_RESERVE_TOKENS


class TestRequiredContextTokens:
    def test_sums_prompt_output_and_margin(self):
        payload = {"messages": [{"role": "user", "content": "x" * 3000}], "max_tokens": 1000}
        prompt = estimate_prompt_tokens(payload)
        assert required_context_tokens(payload) == prompt + 1000 + SAFETY_MARGIN_TOKENS

    def test_none_means_no_opinion(self):
        """Callers skip context filtering on None rather than guessing.

        An unreadable payload is not evidence that a narrow worker is wrong for
        it, so routing must stay as it was.
        """
        assert required_context_tokens({"model": "m"}) is None
        assert required_context_tokens(None) is None
