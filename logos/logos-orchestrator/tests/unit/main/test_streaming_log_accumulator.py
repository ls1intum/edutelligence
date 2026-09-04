"""_StreamingLogAccumulator: SSE parsing for both API surfaces.

Chat Completions streams send delta chunks with a trailing usage chunk
(stream_options.include_usage); Responses-API streams send typed events
(``response.output_text.delta`` for text, ``response.completed`` carrying the
full response including usage). Both must yield usable usage + response
payloads for request logging and rate limiting.
"""

import datetime
import json

import logos as main
from logos.main import _StreamingLogAccumulator, _usage_tokens_from_payload


def _feed_sse(acc: _StreamingLogAccumulator, *events: dict) -> None:
    for event in events:
        acc.feed(f"data: {json.dumps(event)}\n\n".encode())
    acc.feed(b"data: [DONE]\n\n")
    acc.finish()


def test_chat_completions_stream_accumulates_text_and_usage():
    acc = _StreamingLogAccumulator()
    _feed_sse(
        acc,
        {"id": "c1", "choices": [{"delta": {"content": "Hel"}}]},
        {"id": "c1", "choices": [{"delta": {"content": "lo"}}]},
        {"id": "c1", "choices": [], "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}},
    )

    assert acc.full_text == "Hello"
    assert acc.usage() == {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}
    payload = acc.response_payload()
    assert payload["choices"][0]["delta"] == {"content": "Hello"}
    assert payload["usage"]["total_tokens"] == 5


def test_mid_stream_error_frame_is_captured_without_clobbering_earlier_usage():
    # A content filter / context-length error that fires after generation began
    # arrives as a data: {"error": {...}} frame with an HTTP 200 stream. It must
    # not overwrite the usage chunk that preceded it.
    acc = _StreamingLogAccumulator()
    acc.feed(b'data: {"id":"c1","choices":[{"delta":{"content":"Partial"}}]}\n\n')
    acc.feed(b'data: {"id":"c1","choices":[],"usage":{"prompt_tokens":10,"completion_tokens":4,"total_tokens":14}}\n\n')
    acc.feed(b'data: {"error":{"message":"content flagged mid-stream","type":"invalid_request_error"}}\n\n')
    acc.finish()

    assert acc.full_text == "Partial"
    assert acc.upstream_error == {"message": "content flagged mid-stream", "type": "invalid_request_error"}
    assert acc.usage() == {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14}


def test_clean_chat_stream_has_no_upstream_error():
    acc = _StreamingLogAccumulator()
    _feed_sse(
        acc,
        {"id": "c1", "choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]},
        {"id": "c1", "choices": [], "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}},
    )
    assert acc.upstream_error is None


def test_stream_decodes_utf8_code_points_split_across_byte_chunks():
    event = {"id": "c1", "choices": [{"delta": {"content": "Grüße 👋"}}]}
    raw = f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode()
    acc = _StreamingLogAccumulator()

    for byte in raw:
        acc.feed(bytes([byte]))
    acc.finish()

    assert acc.full_text == "Grüße 👋"
    assert "�" not in acc.response_payload()["choices"][0]["delta"]["content"]


def test_responses_stream_uses_terminal_event():
    final_response = {
        "id": "resp_1",
        "object": "response",
        "status": "completed",
        "output": [
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "Hello"}],
            }
        ],
        "usage": {
            "input_tokens": 3,
            "output_tokens": 2,
            "total_tokens": 5,
            "output_tokens_details": {"reasoning_tokens": 0},
        },
    }

    acc = _StreamingLogAccumulator()
    _feed_sse(
        acc,
        {"type": "response.created", "response": {"id": "resp_1", "status": "in_progress"}},
        {"type": "response.output_text.delta", "delta": "Hel"},
        {"type": "response.output_text.delta", "delta": "lo"},
        {"type": "response.completed", "response": final_response},
    )

    assert acc.full_text == "Hello"
    assert acc.usage() == final_response["usage"]
    # The terminal event carries the complete response — logged verbatim.
    assert acc.response_payload() == final_response


def test_responses_stream_billing_from_real_azure_sse():
    """End-to-end billing path on a real Azure /openai/responses stream.

    Event sequence, SSE framing (``event:`` lines before ``data:``), the
    reasoning output item, and the usage numbers are taken verbatim from a
    gpt-5-nano response captured against the production Azure deployment
    (2026-07-09). The billed dict is what set_response_payload writes to the
    usage_tokens table, so its keys must be the Chat Completions names the
    token_prices join is keyed to.
    """
    final_response = {
        "id": "resp_0233a0734033d476",
        "object": "response",
        "status": "completed",
        "model": "gpt-5-nano",
        "output": [
            {"id": "rs_0233a0734033d476", "type": "reasoning", "content": [], "summary": []},
            {
                "id": "msg_0233a0734033d476",
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [{"type": "output_text", "annotations": [], "text": "Hello there everyone"}],
            },
        ],
        "usage": {
            "input_tokens": 13,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens": 701,
            "output_tokens_details": {"reasoning_tokens": 640},
            "total_tokens": 714,
        },
    }
    events = [
        ("response.created", {"type": "response.created", "response": {"id": "resp_0233a0734033d476"}}),
        ("response.in_progress", {"type": "response.in_progress", "response": {"id": "resp_0233a0734033d476"}}),
        (
            "response.output_item.added",
            {"type": "response.output_item.added", "item": {"type": "reasoning"}},
        ),
        ("response.output_text.delta", {"type": "response.output_text.delta", "delta": "Hello "}),
        ("response.output_text.delta", {"type": "response.output_text.delta", "delta": "there "}),
        ("response.output_text.delta", {"type": "response.output_text.delta", "delta": "everyone"}),
        (
            "response.output_text.done",
            {"type": "response.output_text.done", "text": "Hello there everyone"},
        ),
        ("response.completed", {"type": "response.completed", "response": final_response}),
    ]
    raw = "".join(f"event: {name}\ndata: {json.dumps(blob)}\n\n" for name, blob in events).encode()

    acc = _StreamingLogAccumulator()
    # Feed in small chunks so events straddle feed() boundaries, as over HTTP.
    for i in range(0, len(raw), 64):
        acc.feed(raw[i : i + 64])
    acc.finish()

    assert acc.full_text == "Hello there everyone"
    assert acc.response_payload() == final_response
    assert _usage_tokens_from_payload(acc.response_payload()) == {
        "prompt_tokens": 13,
        "completion_tokens": 701,
        "total_tokens": 714,
        "prompt_cached_tokens": 0,
        "completion_reasoning_tokens": 640,
        "billed_requests": 1,
        "billed_output_characters": 20,
    }


def test_responses_stream_cut_off_falls_back_to_accumulated_text():
    acc = _StreamingLogAccumulator()
    acc.feed(b'data: {"type": "response.created", "response": {"id": "resp_1"}}\n\n')
    acc.feed(b'data: {"type": "response.output_text.delta", "delta": "partial"}\n\n')
    acc.finish()

    assert acc.usage() == {}
    assert acc.response_payload() == {"content": "partial"}


def test_responses_stream_failed_event_marks_the_request_failed():
    # response.failed is a terminal event on an HTTP 200 stream: generation
    # began, then the provider gave up. The bytes reach the client but the
    # request is not a success and must not be billed.
    acc = _StreamingLogAccumulator()
    _feed_sse(
        acc,
        {"type": "response.created", "response": {"id": "resp_1", "status": "in_progress"}},
        {"type": "response.output_text.delta", "delta": "partial"},
        {
            "type": "response.failed",
            "response": {
                "id": "resp_1",
                "status": "failed",
                "error": {"code": "server_error", "message": "the model is overloaded"},
            },
        },
    )

    assert acc.upstream_error == {"code": "server_error", "message": "the model is overloaded"}


def test_responses_stream_failed_event_without_error_body_still_fails():
    acc = _StreamingLogAccumulator()
    _feed_sse(
        acc,
        {"type": "response.output_text.delta", "delta": "partial"},
        {"type": "response.failed", "response": {"id": "resp_1", "status": "failed", "error": None}},
    )

    assert acc.upstream_error is not None
    assert isinstance(acc.upstream_error.get("message"), str)


def test_responses_stream_incomplete_event_is_not_a_failure():
    # response.incomplete means the generation stopped at max_output_tokens or a
    # content filter. The partial output is returned and the provider charges
    # for it, so it must NOT be treated as an upstream error.
    acc = _StreamingLogAccumulator()
    final_response = {
        "id": "resp_1",
        "status": "incomplete",
        "incomplete_details": {"reason": "max_output_tokens"},
        "usage": {"input_tokens": 5, "output_tokens": 10, "total_tokens": 15},
    }
    _feed_sse(
        acc,
        {"type": "response.output_text.delta", "delta": "partial"},
        {"type": "response.incomplete", "response": final_response},
    )

    assert acc.upstream_error is None
    assert acc.usage() == final_response["usage"]


def test_responses_terminal_event_returns_eur_cost(monkeypatch):
    class DummyDB:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def get_usage_cost_micro_cents(self, model_id, provider_id, usage, response_at, service_tier=None):
            assert (model_id, provider_id) == (27, 12)
            assert usage == {
                "prompt_tokens": 4,
                "completion_tokens": 6,
                "total_tokens": 10,
                "billed_requests": 1,
            }
            assert response_at.tzinfo == datetime.timezone.utc
            return 250

    monkeypatch.setattr(main, "DBManager", DummyDB)
    enricher = main._StreamingCostEnricher(provider_id=12, model_id=27)
    event = {
        "type": "response.completed",
        "response": {
            "id": "resp-1",
            "usage": {"input_tokens": 4, "output_tokens": 6, "total_tokens": 10},
        },
    }

    chunks = enricher.feed(f"data: {json.dumps(event)}\n\n".encode())
    enriched_event = json.loads(chunks[0].decode().splitlines()[0][6:])

    assert enriched_event["response"]["usage"]["cost"] == 0.0000025
    assert enriched_event["response"]["usage"]["cost_currency"] == "USD"


def test_enricher_skips_output_only_partial_usage_frame(monkeypatch):
    # An Anthropic message_delta reports only output_tokens mid-stream; pricing it
    # alone yields an undercharged, input-less cost. The enricher must leave such
    # a frame untouched (the persisted ledger prices the merged usage correctly).
    class DummyDB:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get_usage_cost_micro_cents(self, *a, **k):  # pragma: no cover - must not be called
            raise AssertionError("partial usage frame should not be priced")

    monkeypatch.setattr(main, "DBManager", DummyDB)
    enricher = main._StreamingCostEnricher(provider_id=12, model_id=27)
    frame = b'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":42}}\n\n'
    out = b"".join(enricher.feed(frame))
    assert out == frame  # forwarded verbatim, no usage.cost injected


def test_enricher_skips_non_terminal_gemini_usage_metadata(monkeypatch):
    class DummyDB:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get_usage_cost_micro_cents(self, *args, **kwargs):  # pragma: no cover
            raise AssertionError("non-terminal Gemini usage should not be priced")

    monkeypatch.setattr(main, "DBManager", DummyDB)
    enricher = main._StreamingCostEnricher(provider_id=12, model_id=27)
    frame = (
        b'data: {"candidates":[{"content":{"parts":[{"text":"partial"}]}}],'
        b'"usageMetadata":{"promptTokenCount":10,"candidatesTokenCount":2}}\n\n'
    )

    assert b"".join(enricher.feed(frame)) == frame


def test_enricher_accepts_terminal_gemini_usage_metadata():
    assert main._StreamingCostEnricher._frame_usage_is_settled(
        {
            "candidates": [{"finishReason": "STOP"}],
            "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 2},
        }
    )


# ── Anthropic Messages streams ───────────────────────────────────────────────
# What Claude Code speaks, so every session set up through the AI-tools page
# arrives in this shape. Usage is split across two events and neither is the
# last one: message_start opens with the prompt size, message_delta settles the
# figures, and message_stop closes the stream carrying nothing. Reading the
# final chunk found message_stop and came away empty, so these requests were
# logged with no tokens at all.


def _anthropic_events(input_tokens: int = 14, output_tokens: int = 2) -> list[dict]:
    """One real stream, captured from vLLM 0.27 through Logos."""
    return [
        {
            "type": "message_start",
            "message": {
                "id": "chatcmpl-8b4942c3bcdac4f3",
                "type": "message",
                "role": "assistant",
                "content": [],
                "model": "Qwen/Qwen3.8-27B",
                "usage": {"input_tokens": input_tokens, "output_tokens": 0},
            },
        },
        {"type": "content_block_start", "content_block": {"type": "text", "text": ""}, "index": 0},
        {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "OK"}, "index": 0},
        {"type": "content_block_stop", "index": 0},
        {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn"},
            "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
        },
        {"type": "message_stop"},
    ]


def test_messages_stream_keeps_usage_past_message_stop():
    acc = _StreamingLogAccumulator()
    _feed_sse(acc, *_anthropic_events())

    usage = acc.usage()
    assert usage["input_tokens"] == 14
    assert usage["output_tokens"] == 2


def test_messages_stream_accumulates_text():
    acc = _StreamingLogAccumulator()
    _feed_sse(acc, *_anthropic_events())

    assert acc.full_text == "OK"


def test_messages_stream_supplies_the_total_anthropic_omits():
    """Anthropic sends no total — it is the sum, so it says it once. Logos
    stores one row per token type and the statistics page reads total_tokens,
    so a stream without it lands as zero tokens used."""
    acc = _StreamingLogAccumulator()
    _feed_sse(acc, *_anthropic_events(input_tokens=100, output_tokens=25))

    assert acc.usage()["total_tokens"] == 125


def test_messages_stream_usage_reaches_the_token_rows():
    """End to end through the mapping that writes usage_tokens: Anthropic's
    field names have to land as the canonical prompt/completion pair."""
    acc = _StreamingLogAccumulator()
    _feed_sse(acc, *_anthropic_events(input_tokens=14, output_tokens=2))

    tokens = _usage_tokens_from_payload(acc.response_payload())

    assert tokens["prompt_tokens"] == 14
    assert tokens["completion_tokens"] == 2
    assert tokens["total_tokens"] == 16


def test_messages_delta_wins_over_message_start():
    """message_start opens with output_tokens 0; the settled count arrives in
    message_delta and must not be shadowed by the earlier event."""
    acc = _StreamingLogAccumulator()
    _feed_sse(acc, *_anthropic_events(input_tokens=14, output_tokens=99))

    assert acc.usage()["output_tokens"] == 99


def test_messages_stream_cut_off_early_keeps_what_it_had():
    """A client that disconnects mid-stream never sends message_delta. The
    prompt size from message_start is still real and worth recording."""
    acc = _StreamingLogAccumulator()
    events = _anthropic_events()[:3]  # message_start, block_start, one delta
    for event in events:
        acc.feed(f"data: {json.dumps(event)}\n\n".encode())
    acc.finish()

    usage = acc.usage()
    assert usage["input_tokens"] == 14
    assert usage["output_tokens"] == 0
    assert acc.full_text == "OK"


def test_messages_stream_survives_split_chunks():
    """Network boundaries do not respect SSE boundaries — the usage event
    arriving in two pieces must still be parsed."""
    acc = _StreamingLogAccumulator()
    blob = json.dumps(
        {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn"},
            "usage": {"input_tokens": 7, "output_tokens": 3},
        }
    )
    line = f"data: {blob}\n\n"
    acc.feed(line[:20].encode())
    acc.feed(line[20:].encode())
    acc.finish()

    assert acc.usage()["output_tokens"] == 3


def test_chat_completions_stream_is_untouched_by_the_messages_path():
    """The two shapes share the parser; adding one must not disturb the other."""
    acc = _StreamingLogAccumulator()
    _feed_sse(
        acc,
        {"id": "c1", "choices": [{"delta": {"content": "Hi"}}]},
        {"id": "c1", "choices": [], "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}},
    )

    assert acc.usage() == {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}
    assert acc.full_text == "Hi"
