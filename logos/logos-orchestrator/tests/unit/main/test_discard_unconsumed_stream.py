"""Discarding a prefetched streaming response must free upstream resources.

``_streaming_response`` peeks the first chunk before returning a
``StreamingResponse``. Closing only the never-started body generator does not
run its ``finally``, so the prefetched upstream iterator and the scheduler
slot would leak without an explicit cleanup path.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from tests.unit.main.test_request_logging import _make_dummy_db, _make_pipeline

import logos as main


@pytest.mark.asyncio
async def test_discard_of_unconsumed_streaming_response_closes_upstream_and_releases_slot(
    monkeypatch,
):
    upstream_closed = False

    class Executor:
        async def execute_streaming(self, url, headers, payload, on_headers=None, status=None):
            nonlocal upstream_closed
            if status is not None:
                status.dispatch_at = main.datetime.datetime.now(main.datetime.timezone.utc)
            if on_headers:
                on_headers({"content-type": "text/event-stream"})
            try:
                yield b'data: {"choices":[{"delta":{"content":"x"}}]}\n\n'
                yield b"data: [DONE]\n\n"
            finally:
                upstream_closed = True

    pipeline, _completion, release_calls = _make_pipeline()
    pipeline.executor = Executor()
    monkeypatch.setattr(main, "_pipeline", pipeline, raising=False)
    monkeypatch.setattr(main, "DBManager", _make_dummy_db())
    monkeypatch.setattr(
        main,
        "_context_resolver",
        SimpleNamespace(prepare_headers_and_payload=lambda context, payload: ({}, payload)),
        raising=False,
    )
    monkeypatch.setattr(main, "model_name_cache", {}, raising=False)

    response = await main._streaming_response(
        SimpleNamespace(
            provider_type="cloud",
            forward_url="http://upstream/v1/chat/completions",
            anthropic_dialect=None,
            messages_upstream=False,
        ),
        {"messages": [{"role": "user", "content": "hi"}], "stream": True},
        42,
        12,
        27,
        -1,
        {"policy": "ok"},
        {
            "request_id": "req-unconsumed",
            "provider_type": "cloud",
            "queue_depth_at_arrival": 0,
            "utilization_at_arrival": 1,
            "is_cold_start": False,
        },
    )

    assert getattr(response, "_logos_unconsumed_cleanup", None) is not None
    # Nobody consumes the body — the keepalive / disconnect path discards it.
    await main._discard_response(response)

    assert upstream_closed, "prefetched upstream iterator was not closed"
    assert release_calls, "scheduler slot was not released"
    assert release_calls[0][0:3] == (27, 12, "cloud")


@pytest.mark.asyncio
async def test_discard_of_unconsumed_logosnode_response_releases_slot(monkeypatch):
    """LogosNode streams do not prefetch, but the scheduler slot is already
    reserved when the response is built — discard must still free it."""

    pipeline, _completion, release_calls = _make_pipeline()
    monkeypatch.setattr(main, "_pipeline", pipeline, raising=False)
    monkeypatch.setattr(main, "DBManager", _make_dummy_db())
    monkeypatch.setattr(
        main,
        "_context_resolver",
        SimpleNamespace(prepare_headers_and_payload=lambda context, payload: ({}, payload)),
        raising=False,
    )
    monkeypatch.setattr(main, "model_name_cache", {}, raising=False)
    # Body must not start — if send_stream_command is touched, the test is wrong.
    monkeypatch.setattr(
        main,
        "_logosnode_registry",
        SimpleNamespace(
            send_stream_command=lambda **kwargs: (_ for _ in ()).throw(
                AssertionError("unconsumed LogosNode body must not dispatch")
            )
        ),
        raising=False,
    )

    response = await main._streaming_response(
        SimpleNamespace(
            provider_type="logosnode",
            lane_id="lane-1",
            anthropic_dialect=None,
            messages_upstream=False,
        ),
        {"messages": [{"role": "user", "content": "hi"}], "stream": True},
        42,
        12,
        27,
        -1,
        {"policy": "ok"},
        {
            "request_id": "req-logosnode-unconsumed",
            "provider_type": "logosnode",
            "queue_depth_at_arrival": 0,
            "utilization_at_arrival": 1,
            "is_cold_start": False,
        },
    )

    assert getattr(response, "_logos_unconsumed_cleanup", None) is not None
    await main._discard_response(response)

    assert release_calls, "scheduler slot was not released"
    assert release_calls[0][0:3] == (27, 12, "logosnode")


@pytest.mark.asyncio
async def test_cancel_at_scheduling_comment_discards_prefetched_http_stream(monkeypatch):
    """Cancel while the scheduling comment is yielded must run unconsumed
    cleanup — closing only the never-started body leaves the peeked upstream
    and the reserved slot behind."""
    import asyncio

    from fastapi.responses import StreamingResponse

    upstream_closed = False

    class Executor:
        async def execute_streaming(self, url, headers, payload, on_headers=None, status=None):
            nonlocal upstream_closed
            if status is not None:
                status.dispatch_at = main.datetime.datetime.now(main.datetime.timezone.utc)
            if on_headers:
                on_headers({"content-type": "text/event-stream"})
            try:
                yield b'data: {"choices":[{"delta":{"content":"x"}}]}\n\n'
                await asyncio.sleep(30)
                yield b"data: [DONE]\n\n"
            finally:
                upstream_closed = True

    pipeline, _completion, release_calls = _make_pipeline()
    pipeline.executor = Executor()
    monkeypatch.setattr(main, "_pipeline", pipeline, raising=False)
    monkeypatch.setattr(main, "DBManager", _make_dummy_db())
    monkeypatch.setattr(
        main,
        "_context_resolver",
        SimpleNamespace(prepare_headers_and_payload=lambda context, payload: ({}, payload)),
        raising=False,
    )
    monkeypatch.setattr(main, "model_name_cache", {}, raising=False)
    monkeypatch.setattr(main, "_KEEPALIVE_INTERVAL_S", 0.05)
    monkeypatch.setattr(main, "_CLIENT_DISCONNECT_POLL_SECONDS", 0.001)

    async def route_via_streaming_response(**kwargs):
        return await main._streaming_response(
            SimpleNamespace(
                provider_type="cloud",
                forward_url="http://upstream/v1/chat/completions",
                anthropic_dialect=None,
                messages_upstream=False,
            ),
            {"messages": [{"role": "user", "content": "hi"}], "stream": True},
            42,
            12,
            27,
            -1,
            {"policy": "ok"},
            {
                "request_id": "req-comment-cancel",
                "provider_type": "cloud",
                "queue_depth_at_arrival": 0,
                "utilization_at_arrival": 1,
                "is_cold_start": False,
                "estimated_ttft_ms": 50,
                "warmth_state": 1,
            },
        )

    monkeypatch.setattr(main, "route_and_execute", route_via_streaming_response)

    class _Client:
        async def is_disconnected(self) -> bool:
            return False

    response = await main._keepalive_streaming_response(
        _Client(), log_id=1, request_id="req-comment-cancel", path="chat/completions"
    )
    assert isinstance(response, StreamingResponse)

    agen = response.body_iterator
    first = await agen.__anext__()
    assert b"logos-schedule" in first
    await agen.aclose()

    assert upstream_closed, "prefetched upstream stayed open after comment-yield cancel"
    assert release_calls, "scheduler slot was not released after comment-yield cancel"
