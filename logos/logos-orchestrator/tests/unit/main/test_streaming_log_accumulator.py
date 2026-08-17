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
    }


def test_responses_stream_cut_off_falls_back_to_accumulated_text():
    acc = _StreamingLogAccumulator()
    acc.feed(b'data: {"type": "response.created", "response": {"id": "resp_1"}}\n\n')
    acc.feed(b'data: {"type": "response.output_text.delta", "delta": "partial"}\n\n')
    acc.finish()

    assert acc.usage() == {}
    assert acc.response_payload() == {"content": "partial"}


def test_responses_terminal_event_returns_eur_cost(monkeypatch):
    class DummyDB:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def get_usage_cost_micro_cents(self, model_id, provider_id, usage, response_at):
            assert (model_id, provider_id) == (27, 12)
            assert usage == {"prompt_tokens": 4, "completion_tokens": 6, "total_tokens": 10}
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
    assert enriched_event["response"]["usage"]["cost_currency"] == "EUR"
