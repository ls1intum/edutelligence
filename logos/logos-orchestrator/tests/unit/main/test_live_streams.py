"""The in-flight view of a streaming request.

A finished request's usage is in the database; one still running is only in the
process the chunks pass through. Without this the statistics feed shows a row
with no numbers for the whole minute a long generation takes, then fills it in
at once when the request ends.

The exact completion count arrives only with the terminal usage event, so until
then the text deltas stand in for it — an approximation that is never stored or
billed, only shown while the request runs.
"""

from __future__ import annotations

import json

from logos.main import _LiveStreamRegistry, _StreamingLogAccumulator


def _feed(acc: _StreamingLogAccumulator, *events: dict) -> None:
    for event in events:
        acc.feed(f"data: {json.dumps(event)}\n\n".encode())


# ── Counting mid-stream ──────────────────────────────────────────────────────


def test_completion_count_grows_with_the_deltas():
    """The point of the whole thing: a number that moves while the request runs."""
    acc = _StreamingLogAccumulator()

    _feed(acc, {"type": "message_start", "message": {"usage": {"input_tokens": 14, "output_tokens": 0}}})
    assert acc.streamed_tokens() == {"prompt_tokens": 14, "completion_tokens": 0}

    _feed(acc, {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "one"}})
    assert acc.streamed_tokens()["completion_tokens"] == 1

    _feed(acc, {"type": "content_block_delta", "delta": {"type": "text_delta", "text": " two"}})
    assert acc.streamed_tokens()["completion_tokens"] == 2


def test_the_settled_count_replaces_the_estimate():
    """Once the terminal event lands, the real figure wins — the delta count was
    only ever a stand-in for the wait."""
    acc = _StreamingLogAccumulator()
    _feed(
        acc,
        {"type": "message_start", "message": {"usage": {"input_tokens": 14, "output_tokens": 0}}},
        {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "a"}},
        {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "b"}},
        # Speculative decoding: three real tokens behind two deltas.
        {"type": "message_delta", "delta": {}, "usage": {"input_tokens": 14, "output_tokens": 3}},
    )

    assert acc.streamed_tokens() == {"prompt_tokens": 14, "completion_tokens": 3}


def test_it_counts_chat_completions_deltas_too():
    acc = _StreamingLogAccumulator()
    _feed(
        acc,
        {"choices": [{"delta": {"content": "Hel"}}]},
        {"choices": [{"delta": {"content": "lo"}}]},
    )

    assert acc.streamed_tokens()["completion_tokens"] == 2


def test_it_counts_responses_api_deltas_too():
    acc = _StreamingLogAccumulator()
    _feed(
        acc,
        {"type": "response.output_text.delta", "delta": "Hel"},
        {"type": "response.output_text.delta", "delta": "lo"},
    )

    assert acc.streamed_tokens()["completion_tokens"] == 2


# ── The registry ─────────────────────────────────────────────────────────────


def test_a_running_request_appears_with_its_counts():
    reg = _LiveStreamRegistry()
    reg.start("req-1", "Qwen/Qwen3.8-27B")
    reg.update("req-1", {"prompt_tokens": 14, "completion_tokens": 5})

    (row,) = reg.snapshot()

    assert row["request_id"] == "req-1"
    assert row["model_name"] == "Qwen/Qwen3.8-27B"
    assert row["prompt_tokens"] == 14
    assert row["completion_tokens"] == 5


def test_a_finished_request_leaves_the_view():
    reg = _LiveStreamRegistry()
    reg.start("req-1", "m")
    reg.update("req-1", {"prompt_tokens": 1, "completion_tokens": 1})
    reg.finish("req-1")

    assert reg.snapshot() == []


def test_updates_for_an_unknown_request_are_ignored():
    """finish() runs in a `finally`, so a late update can arrive after it. It
    must not resurrect the entry and leave it in the view forever."""
    reg = _LiveStreamRegistry()
    reg.start("req-1", "m")
    reg.finish("req-1")
    reg.update("req-1", {"prompt_tokens": 1, "completion_tokens": 1})

    assert reg.snapshot() == []


def test_requests_without_an_id_are_not_tracked():
    reg = _LiveStreamRegistry()
    reg.start(None, "m")
    reg.update(None, {"prompt_tokens": 1, "completion_tokens": 1})

    assert reg.snapshot() == []


def test_the_rate_is_unknown_before_anything_is_generated():
    """No tokens yet means no span to divide by. None, not zero: the request is
    queued or still on its first token, which is not a rate of zero."""
    reg = _LiveStreamRegistry()
    reg.start("req-1", "m")
    reg.update("req-1", {"prompt_tokens": 14, "completion_tokens": 0})

    assert reg.snapshot()[0]["tokens_per_second"] is None


def test_the_rate_is_measured_from_the_first_token():
    """Not from arrival: a request that waited a minute for a lane to warm up
    would otherwise report a rate nobody was seeing."""
    clock = {"now": 1000.0}

    reg = _LiveStreamRegistry(now=lambda: clock["now"])
    reg.start("req-1", "m")
    clock["now"] += 60.0  # a minute of queueing, no tokens
    reg.update("req-1", {"prompt_tokens": 14, "completion_tokens": 1})
    clock["now"] += 10.0  # ten seconds of generating
    reg.update("req-1", {"prompt_tokens": 14, "completion_tokens": 201})

    row = reg.snapshot()[0]

    # 201 tokens over the ten seconds since generation began — not over the
    # seventy since the request arrived.
    assert row["tokens_per_second"] == 20.1
    assert row["elapsed_seconds"] == 70.0


def test_several_requests_are_tracked_independently():
    reg = _LiveStreamRegistry()
    reg.start("req-1", "model-a")
    reg.start("req-2", "model-b")
    reg.update("req-1", {"prompt_tokens": 1, "completion_tokens": 10})
    reg.update("req-2", {"prompt_tokens": 2, "completion_tokens": 20})

    by_id = {row["request_id"]: row for row in reg.snapshot()}

    assert by_id["req-1"]["completion_tokens"] == 10
    assert by_id["req-2"]["completion_tokens"] == 20
