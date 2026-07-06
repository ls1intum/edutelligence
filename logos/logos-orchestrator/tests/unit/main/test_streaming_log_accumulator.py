"""_StreamingLogAccumulator: SSE parsing for both API surfaces.

Chat Completions streams send delta chunks with a trailing usage chunk
(stream_options.include_usage); Responses-API streams send typed events
(``response.output_text.delta`` for text, ``response.completed`` carrying the
full response including usage). Both must yield usable usage + response
payloads for request logging and rate limiting.
"""

import json

from logos.main import _StreamingLogAccumulator


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


def test_responses_stream_cut_off_falls_back_to_accumulated_text():
    acc = _StreamingLogAccumulator()
    acc.feed(b'data: {"type": "response.created", "response": {"id": "resp_1"}}\n\n')
    acc.feed(b'data: {"type": "response.output_text.delta", "delta": "partial"}\n\n')
    acc.finish()

    assert acc.usage() == {}
    assert acc.response_payload() == {"content": "partial"}
