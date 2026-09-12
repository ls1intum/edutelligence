"""An abandoned request must be aborted on the worker, not just locally.

`_execute_cancelling_on_disconnect` already stops the orchestrator from
reading a response whose client is gone, and for the HTTP path that is
enough: closing the httpx context closes the connection and vLLM aborts the
sequence by itself. Worker requests have no such connection — every request
to a worker is multiplexed over one WebSocket — so dropping the local queue
only stops *us* from reading. The lane keeps generating, holding a KV slot
for the full length of a response nobody will read; under a retry storm each
abandoned attempt eats the capacity its own retry needs.

These tests pin the missing half: the orchestrator tells the worker to stop.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from logos.errors import UpstreamStreamError
from logos.logosnode_registry import CANCEL_COMMAND_ACTION, LogosNodeRuntimeRegistry, ProviderSession

PROVIDER_ID = 7


class _FakeWebSocket:
    """Records outbound frames and lets a test answer command RPCs."""

    def __init__(self, provider_id: int = PROVIDER_ID) -> None:
        self.sent: list[dict] = []
        self.auto_ack = True
        self._registry: LogosNodeRuntimeRegistry | None = None
        self.provider_id = provider_id
        # Set from send_json the moment the command frame is on the wire.
        # Waiting on these instead of a bare asyncio.sleep(0) keeps the tests
        # deterministic: a sleep(0) yields only once, and the dispatch task
        # may not have reached send_json yet (it awaits the session lookup
        # and the send lock first).
        self.stream_command_sent = asyncio.Event()
        self.infer_command_sent = asyncio.Event()

    def bind(self, registry: LogosNodeRuntimeRegistry) -> None:
        self._registry = registry

    async def send_json(self, message: dict) -> None:
        self.sent.append(message)
        action = message.get("action")
        if action == "infer_stream":
            self.stream_command_sent.set()
        elif action == "infer":
            self.infer_command_sent.set()
        if self.auto_ack and self._registry is not None and action == CANCEL_COMMAND_ACTION:
            # Answer the cancel RPC the way a worker would, so the
            # fire-and-forget task completes instead of timing out.
            await self._registry.on_command_result(
                self.provider_id,
                {
                    "cmd_id": message["cmd_id"],
                    "success": True,
                    "result": {"cancelled": True, "target_cmd_id": message["params"]["target_cmd_id"]},
                },
            )

    def cancel_frames(self) -> list[dict]:
        return [m for m in self.sent if m.get("action") == CANCEL_COMMAND_ACTION]


def _registry_with_session(*, actions: set[str] | None = None) -> tuple[LogosNodeRuntimeRegistry, _FakeWebSocket]:
    registry = LogosNodeRuntimeRegistry()
    websocket = _FakeWebSocket()
    websocket.bind(registry)
    session = ProviderSession(
        provider_id=PROVIDER_ID,
        worker_id="worker-a",
        websocket=websocket,
        actions={CANCEL_COMMAND_ACTION} if actions is None else actions,
    )
    registry._sessions[PROVIDER_ID] = session
    return registry, websocket


async def _feed(registry: LogosNodeRuntimeRegistry, cmd_id: str, event: dict) -> None:
    """Push one worker frame into the queue behind ``cmd_id``."""
    queue = registry._sessions[PROVIDER_ID].pending_streams[cmd_id]
    await queue.put(event)


async def _drain_pending_tasks() -> None:
    """Let fire-and-forget cancellation tasks run to completion."""
    for _ in range(10):
        await asyncio.sleep(0)


def _sent_stream_cmd_id(websocket: _FakeWebSocket) -> str:
    return next(m["cmd_id"] for m in websocket.sent if m.get("action") == "infer_stream")


# ---------------------------------------------------------------------------
# Streaming path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_abandoned_stream_is_cancelled_on_the_worker():
    """Closing the generator early — what a client disconnect does — must
    reach the worker as a cancellation."""
    registry, websocket = _registry_with_session()

    stream = registry.send_stream_command(PROVIDER_ID, "infer_stream", {"lane_id": "lane-a"})
    consumer = asyncio.ensure_future(stream.__anext__())
    await asyncio.wait_for(websocket.stream_command_sent.wait(), timeout=1)
    cmd_id = _sent_stream_cmd_id(websocket)
    await _feed(registry, cmd_id, {"type": "stream_chunk", "chunk": b"tok"})
    assert await consumer == b"tok"

    await stream.aclose()  # the consumer walked away mid-stream
    await _drain_pending_tasks()

    frames = websocket.cancel_frames()
    assert len(frames) == 1
    assert frames[0]["params"] == {"target_cmd_id": cmd_id}


@pytest.mark.asyncio
async def test_a_stream_that_finished_normally_is_not_cancelled():
    """No spurious RPC for a request the worker already completed."""
    registry, websocket = _registry_with_session()

    stream = registry.send_stream_command(PROVIDER_ID, "infer_stream", {"lane_id": "lane-a"})
    consumer = asyncio.ensure_future(stream.__anext__())
    await asyncio.wait_for(websocket.stream_command_sent.wait(), timeout=1)
    cmd_id = _sent_stream_cmd_id(websocket)
    await _feed(registry, cmd_id, {"type": "stream_chunk", "chunk": b"tok"})
    await consumer
    await _feed(registry, cmd_id, {"type": "stream_end", "success": True})
    with pytest.raises(StopAsyncIteration):
        await stream.__anext__()

    await _drain_pending_tasks()
    assert websocket.cancel_frames() == []


@pytest.mark.asyncio
async def test_a_worker_reported_stream_failure_is_not_cancelled():
    """A failing stream_end is still a terminal answer — the worker is done."""
    registry, websocket = _registry_with_session()

    stream = registry.send_stream_command(PROVIDER_ID, "infer_stream", {"lane_id": "lane-a"})
    consumer = asyncio.ensure_future(stream.__anext__())
    await asyncio.wait_for(websocket.stream_command_sent.wait(), timeout=1)
    cmd_id = _sent_stream_cmd_id(websocket)
    await _feed(registry, cmd_id, {"type": "stream_end", "success": False, "error": "lane died"})
    with pytest.raises(Exception, match="lane died"):
        await consumer

    await _drain_pending_tasks()
    assert websocket.cancel_frames() == []


@pytest.mark.asyncio
async def test_a_worker_without_the_capability_is_left_alone():
    """Rolling upgrade: an older worker never advertised the action, and
    sending it would only come back as 'Unsupported bridge command'."""
    registry, websocket = _registry_with_session(actions=set())

    stream = registry.send_stream_command(PROVIDER_ID, "infer_stream", {"lane_id": "lane-a"})
    consumer = asyncio.ensure_future(stream.__anext__())
    await asyncio.wait_for(websocket.stream_command_sent.wait(), timeout=1)
    cmd_id = _sent_stream_cmd_id(websocket)
    await _feed(registry, cmd_id, {"type": "stream_chunk", "chunk": b"tok"})
    await consumer

    await stream.aclose()
    await _drain_pending_tasks()
    assert websocket.cancel_frames() == []


@pytest.mark.asyncio
async def test_cancellation_clears_the_pending_stream_entry():
    """The per-request queue must not outlive the request either."""
    registry, websocket = _registry_with_session()

    stream = registry.send_stream_command(PROVIDER_ID, "infer_stream", {"lane_id": "lane-a"})
    consumer = asyncio.ensure_future(stream.__anext__())
    await asyncio.wait_for(websocket.stream_command_sent.wait(), timeout=1)
    cmd_id = _sent_stream_cmd_id(websocket)
    await _feed(registry, cmd_id, {"type": "stream_chunk", "chunk": b"tok"})
    await consumer

    await stream.aclose()
    await _drain_pending_tasks()
    assert cmd_id not in registry._sessions[PROVIDER_ID].pending_streams


# ---------------------------------------------------------------------------
# The absolute execution deadline
#
# ``timeout_seconds`` is a per-read idle bound: a worker that keeps streaming
# can never trip it, so without the deadline a stream could run indefinitely
# past the retry budget. The deadline is an absolute wall instead — checked
# and clamped on every read, never reset by activity.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_spent_deadline_fails_the_stream_before_its_first_chunk():
    import time

    from logos.errors import RetryDeadlineExceeded

    registry, websocket = _registry_with_session()
    stream = registry.send_stream_command(
        PROVIDER_ID,
        "infer_stream",
        {"lane_id": "lane-a"},
        timeout_seconds=30,
        deadline_at=time.monotonic() - 1.0,  # spent before the first read
    )
    consumer = asyncio.ensure_future(stream.__anext__())
    await asyncio.wait_for(websocket.stream_command_sent.wait(), timeout=1)
    with pytest.raises(RetryDeadlineExceeded):
        await asyncio.wait_for(consumer, timeout=1)
    await _drain_pending_tasks()


@pytest.mark.asyncio
async def test_chunks_cannot_push_the_stream_past_the_deadline():
    """The scenario an idle bound misses: a worker sending more often than
    the idle timeout can ever fire. The stream must still stop at the
    absolute deadline, however steadily the worker delivers."""
    import time

    from logos.errors import RetryDeadlineExceeded

    registry, websocket = _registry_with_session()
    deadline = time.monotonic() + 0.3
    stream = registry.send_stream_command(
        PROVIDER_ID,
        "infer_stream",
        {"lane_id": "lane-a"},
        timeout_seconds=30,  # an idle bound the steady chunks never trip
        deadline_at=deadline,
    )
    consumer = asyncio.ensure_future(stream.__anext__())
    await asyncio.wait_for(websocket.stream_command_sent.wait(), timeout=1)
    cmd_id = _sent_stream_cmd_id(websocket)

    received = []
    deadline_hit = False
    while time.monotonic() < deadline + 2.0:
        await _feed(registry, cmd_id, {"type": "stream_chunk", "chunk": b"t"})
        try:
            received.append(await asyncio.wait_for(consumer, timeout=0.15))
            consumer = asyncio.ensure_future(stream.__anext__())
        except RetryDeadlineExceeded:
            deadline_hit = True
            break
        except asyncio.TimeoutError:
            continue  # the read is still open: feed it more to stay alive

    assert deadline_hit, "the steady stream ran past its deadline"
    assert received, "the stream delivered nothing before the wall"
    await _drain_pending_tasks()


@pytest.mark.asyncio
async def test_a_deadline_reached_during_a_blocked_read_keeps_its_identity():
    """When the wall is crossed while a read is still blocked (the read was
    clamped to the remaining time), the failure must stay
    ``RetryDeadlineExceeded``, not be rewrapped as a worker-offline timeout:
    the pre-token loop treats the two differently — a spent deadline is not
    same-lane-retried, a flaky worker is."""
    import time

    from logos.errors import RetryDeadlineExceeded

    registry, websocket = _registry_with_session()
    stream = registry.send_stream_command(
        PROVIDER_ID,
        "infer_stream",
        {"lane_id": "lane-a"},
        timeout_seconds=30,  # an idle bound the deadline reaches first
        deadline_at=time.monotonic() + 0.3,
    )
    consumer = asyncio.ensure_future(stream.__anext__())
    await asyncio.wait_for(websocket.stream_command_sent.wait(), timeout=1)
    # No chunk is ever fed: the read stays blocked until the clamped deadline
    # fires.
    with pytest.raises(RetryDeadlineExceeded):
        await asyncio.wait_for(consumer, timeout=2)
    await _drain_pending_tasks()


@pytest.mark.asyncio
async def test_an_idle_read_with_the_deadline_ahead_still_reports_the_worker_offline():
    """The deadline clamp must not steal a genuine idle timeout: a read that
    runs the full idle bound while the deadline is still far ahead is the
    worker going quiet, and stays a ``LogosNodeOfflineError`` — which the
    pre-token loop is allowed to same-lane-retry."""
    import time

    from logos.logosnode_registry import LogosNodeOfflineError

    registry, websocket = _registry_with_session()
    stream = registry.send_stream_command(
        PROVIDER_ID,
        "infer_stream",
        {"lane_id": "lane-a"},
        timeout_seconds=1,  # the idle bound fires well before the deadline
        deadline_at=time.monotonic() + 60,
    )
    consumer = asyncio.ensure_future(stream.__anext__())
    await asyncio.wait_for(websocket.stream_command_sent.wait(), timeout=1)
    # No chunk is fed: the idle bound fires first, with the deadline still
    # far ahead.
    with pytest.raises(LogosNodeOfflineError):
        await asyncio.wait_for(consumer, timeout=5)
    await _drain_pending_tasks()


# ---------------------------------------------------------------------------
# A lane can answer with an error status instead of tokens
#
# The worker sends the status in stream_start, the error body as the following
# chunk, then a failing stream_end. That status used to be discarded, so the
# error body was yielded as a normal 200 stream and the transient status was
# never retried. A non-2xx start must now surface as an UpstreamStreamError
# before any body bytes are committed.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_200_stream_start_passes_through_to_the_body():
    """A 200 stream_start is not an error: the body is yielded as-is."""
    registry, websocket = _registry_with_session()

    stream = registry.send_stream_command(PROVIDER_ID, "infer_stream", {"lane_id": "lane-a"})
    consumer = asyncio.ensure_future(stream.__anext__())
    await asyncio.wait_for(websocket.stream_command_sent.wait(), timeout=1)
    cmd_id = _sent_stream_cmd_id(websocket)
    await _feed(registry, cmd_id, {"type": "stream_start", "status_code": 200})
    await _feed(registry, cmd_id, {"type": "stream_chunk", "chunk": b"tok"})
    assert await consumer == b"tok"
    await stream.aclose()


@pytest.mark.asyncio
async def test_a_429_stream_start_surfaces_as_upstream_error_not_a_200():
    """A 429 answer raises before any body bytes are yielded, and keeps its
    status and error body so the caller surfaces 429 (not a 200, not 502)."""
    registry, websocket = _registry_with_session()

    stream = registry.send_stream_command(PROVIDER_ID, "infer_stream", {"lane_id": "lane-a"})
    consumer = asyncio.ensure_future(stream.__anext__())
    await asyncio.wait_for(websocket.stream_command_sent.wait(), timeout=1)
    cmd_id = _sent_stream_cmd_id(websocket)
    await _feed(registry, cmd_id, {"type": "stream_start", "status_code": 429})
    await _feed(
        registry,
        cmd_id,
        {"type": "stream_chunk", "chunk": b'{"error": {"message": "rate limited", "type": "rate_limit_error"}}'},
    )
    await _feed(registry, cmd_id, {"type": "stream_end", "success": False, "error": "HTTP 429"})
    with pytest.raises(UpstreamStreamError) as excinfo:
        await consumer
    assert excinfo.value.status_code == 429
    assert excinfo.value.body == {"error": {"message": "rate limited", "type": "rate_limit_error"}}
    await _drain_pending_tasks()


@pytest.mark.asyncio
async def test_a_5xx_stream_start_surfaces_as_upstream_error_not_a_200():
    """A 5xx answer is an upstream failure, surfaced with its status; a
    non-JSON error body is passed through as-is for the caller to coerce."""
    registry, websocket = _registry_with_session()

    stream = registry.send_stream_command(PROVIDER_ID, "infer_stream", {"lane_id": "lane-a"})
    consumer = asyncio.ensure_future(stream.__anext__())
    await asyncio.wait_for(websocket.stream_command_sent.wait(), timeout=1)
    cmd_id = _sent_stream_cmd_id(websocket)
    await _feed(registry, cmd_id, {"type": "stream_start", "status_code": 503})
    await _feed(registry, cmd_id, {"type": "stream_chunk", "chunk": b"upstream unavailable"})
    await _feed(registry, cmd_id, {"type": "stream_end", "success": False, "error": "HTTP 503"})
    with pytest.raises(UpstreamStreamError) as excinfo:
        await consumer
    assert excinfo.value.status_code == 503
    assert excinfo.value.body == b"upstream unavailable"
    await _drain_pending_tasks()


@pytest.mark.asyncio
async def test_a_3xx_stream_start_surfaces_as_upstream_error_not_a_200():
    """A redirect the worker did not follow is not a token stream: the 3xx
    answer must surface as an error before any body bytes are committed, not
    be yielded as a successful 200 stream."""
    registry, websocket = _registry_with_session()

    stream = registry.send_stream_command(PROVIDER_ID, "infer_stream", {"lane_id": "lane-a"})
    consumer = asyncio.ensure_future(stream.__anext__())
    await asyncio.wait_for(websocket.stream_command_sent.wait(), timeout=1)
    cmd_id = _sent_stream_cmd_id(websocket)
    await _feed(registry, cmd_id, {"type": "stream_start", "status_code": 302})
    await _feed(registry, cmd_id, {"type": "stream_chunk", "chunk": b"Found. Move to http://other-host"})
    await _feed(registry, cmd_id, {"type": "stream_end", "success": False, "error": "HTTP 302"})
    with pytest.raises(UpstreamStreamError) as excinfo:
        await consumer
    assert excinfo.value.status_code == 302
    assert excinfo.value.body == b"Found. Move to http://other-host"
    await _drain_pending_tasks()


@pytest.mark.asyncio
async def test_a_429_lane_answer_is_a_pre_stream_error_not_a_committed_200(monkeypatch):
    """End to end: a lane that answers 429 before any token must come back as
    a 429 JSON error — not a committed 200 StreamingResponse — so the internal
    retry sees the transient status and re-dispatches instead of the client
    eating an error body as a success."""
    from fastapi.responses import JSONResponse, StreamingResponse
    from tests.unit.main.test_request_logging import _make_dummy_db, _make_pipeline

    import logos as main

    registry, websocket = _registry_with_session()
    monkeypatch.setattr(main, "DBManager", _make_dummy_db())
    monkeypatch.setattr(
        main,
        "_context_resolver",
        SimpleNamespace(prepare_headers_and_payload=lambda context, payload: ({}, payload)),
        raising=False,
    )
    monkeypatch.setattr(main, "_logosnode_registry", registry, raising=False)
    pipeline, _completion_calls, _release_calls = _make_pipeline()
    monkeypatch.setattr(main, "_pipeline", pipeline, raising=False)

    response_task = asyncio.ensure_future(
        main._streaming_response(
            SimpleNamespace(
                provider_id=PROVIDER_ID, provider_type="logosnode", lane_id="lane-1", anthropic_dialect=None
            ),
            {"messages": [{"role": "user", "content": "hi"}]},
            42,
            PROVIDER_ID,
            27,
            -1,
            {"policy": "ok"},
            {
                "request_id": "req-429",
                "provider_type": "logosnode",
                "queue_depth_at_arrival": 0,
                "utilization_at_arrival": 1,
                "is_cold_start": False,
            },
        )
    )
    await asyncio.wait_for(websocket.stream_command_sent.wait(), timeout=1)
    cmd_id = _sent_stream_cmd_id(websocket)
    await _feed(registry, cmd_id, {"type": "stream_start", "status_code": 429})
    await _feed(registry, cmd_id, {"type": "stream_chunk", "chunk": b'{"error": {"message": "rate limited"}}'})
    await _feed(registry, cmd_id, {"type": "stream_end", "success": False, "error": "HTTP 429"})

    response = await asyncio.wait_for(response_task, timeout=2)
    await _drain_pending_tasks()

    assert not isinstance(response, StreamingResponse), "the 429 was committed as a 200 stream"
    assert isinstance(response, JSONResponse)
    assert response.status_code == 429


@pytest.mark.asyncio
async def test_a_role_only_first_frame_is_not_a_committed_200_when_the_lane_then_fails(monkeypatch):
    """End to end: a chat stream can open with a role-only delta (empty
    content — what a mock provider emits). That frame carries no generated
    output: if the lane then fails before its first content token, the
    answer must still come back as a pre-stream JSON error the internal
    retry can re-dispatch, not a committed 200 stream — there is no text
    prefix to resume from once the 200 is out."""
    from fastapi.responses import JSONResponse, StreamingResponse
    from tests.unit.main.test_request_logging import _make_dummy_db, _make_pipeline

    import logos as main

    registry, websocket = _registry_with_session()
    monkeypatch.setattr(main, "DBManager", _make_dummy_db())
    monkeypatch.setattr(
        main,
        "_context_resolver",
        SimpleNamespace(prepare_headers_and_payload=lambda context, payload: ({}, payload)),
        raising=False,
    )
    monkeypatch.setattr(main, "_logosnode_registry", registry, raising=False)
    # One pre-token attempt: the test pins the buffering, not the same-lane
    # retry that exists for the just-woken race.
    monkeypatch.setattr(main, "_LOGOSNODE_PRETOKEN_RETRIES", 0, raising=False)
    pipeline, _completion_calls, _release_calls = _make_pipeline()
    monkeypatch.setattr(main, "_pipeline", pipeline, raising=False)

    response_task = asyncio.ensure_future(
        main._streaming_response(
            SimpleNamespace(
                provider_id=PROVIDER_ID, provider_type="logosnode", lane_id="lane-1", anthropic_dialect=None
            ),
            {"messages": [{"role": "user", "content": "hi"}]},
            42,
            PROVIDER_ID,
            27,
            -1,
            {"policy": "ok"},
            {
                "request_id": "req-roleonly",
                "provider_type": "logosnode",
                "queue_depth_at_arrival": 0,
                "utilization_at_arrival": 1,
                "is_cold_start": False,
            },
        )
    )
    await asyncio.wait_for(websocket.stream_command_sent.wait(), timeout=1)
    cmd_id = _sent_stream_cmd_id(websocket)
    await _feed(registry, cmd_id, {"type": "stream_start", "status_code": 200})
    # First frame: a role-only delta — no generated content yet.
    await _feed(
        registry,
        cmd_id,
        {
            "type": "stream_chunk",
            "chunk": (
                b'data: {"id": "chatcmpl-1", "object": "chat.completion.chunk", '
                b'"choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}}]}\n\n'
            ),
        },
    )
    # Worker failure before the first content token.
    await _feed(registry, cmd_id, {"type": "stream_end", "success": False, "error": "lane died"})

    response = await asyncio.wait_for(response_task, timeout=2)
    await _drain_pending_tasks()

    assert not isinstance(
        response, StreamingResponse
    ), "the failure after a role-only frame was committed as a 200 stream"
    assert isinstance(response, JSONResponse)
    assert response.status_code == 502


@pytest.mark.asyncio
async def test_a_split_first_frame_is_not_a_committed_200_when_the_lane_then_fails(monkeypatch):
    """End to end: the worker forwards each ``aiter_bytes()`` transport
    chunk unchanged, so a role-only event can arrive split mid-JSON. The
    first fragment is not a complete frame — it proves nothing and must be
    buffered, not treated as output: if the lane then fails before its first
    content token, the answer must still come back as a pre-stream JSON
    error the internal retry can re-dispatch."""
    from fastapi.responses import JSONResponse, StreamingResponse
    from tests.unit.main.test_request_logging import _make_dummy_db, _make_pipeline

    import logos as main

    registry, websocket = _registry_with_session()
    monkeypatch.setattr(main, "DBManager", _make_dummy_db())
    monkeypatch.setattr(
        main,
        "_context_resolver",
        SimpleNamespace(prepare_headers_and_payload=lambda context, payload: ({}, payload)),
        raising=False,
    )
    monkeypatch.setattr(main, "_logosnode_registry", registry, raising=False)
    # One pre-token attempt: the test pins the buffering, not the same-lane
    # retry that exists for the just-woken race.
    monkeypatch.setattr(main, "_LOGOSNODE_PRETOKEN_RETRIES", 0, raising=False)
    pipeline, _completion_calls, _release_calls = _make_pipeline()
    monkeypatch.setattr(main, "_pipeline", pipeline, raising=False)

    response_task = asyncio.ensure_future(
        main._streaming_response(
            SimpleNamespace(
                provider_id=PROVIDER_ID, provider_type="logosnode", lane_id="lane-1", anthropic_dialect=None
            ),
            {"messages": [{"role": "user", "content": "hi"}]},
            42,
            PROVIDER_ID,
            27,
            -1,
            {"policy": "ok"},
            {
                "request_id": "req-splitfragment",
                "provider_type": "logosnode",
                "queue_depth_at_arrival": 0,
                "utilization_at_arrival": 1,
                "is_cold_start": False,
            },
        )
    )
    await asyncio.wait_for(websocket.stream_command_sent.wait(), timeout=1)
    cmd_id = _sent_stream_cmd_id(websocket)
    await _feed(registry, cmd_id, {"type": "stream_start", "status_code": 200})
    # First transport chunk: the role-only frame split mid-JSON — an
    # incomplete line that is not yet a frame at all.
    await _feed(
        registry,
        cmd_id,
        {
            "type": "stream_chunk",
            "chunk": (
                b'data: {"id": "chatcmpl-1", "object": "chat.completion.chunk", '
                b'"choices": [{"index": 0, "delta": {"ro'
            ),
        },
    )
    # Worker failure before the first content token.
    await _feed(registry, cmd_id, {"type": "stream_end", "success": False, "error": "lane died"})

    response = await asyncio.wait_for(response_task, timeout=2)
    await _drain_pending_tasks()

    assert not isinstance(
        response, StreamingResponse
    ), "the failure after an incomplete first fragment was committed as a 200 stream"
    assert isinstance(response, JSONResponse)
    assert response.status_code == 502


@pytest.mark.asyncio
async def test_a_split_first_frame_is_held_until_it_completes_then_replayed(monkeypatch):
    """End to end: a role-only frame split across two transport chunks is
    held back as a fragment until the second chunk completes it; when the
    content delta then arrives, the 200 is committed with the held frames
    replayed ahead of it — in order, with nothing lost."""
    from fastapi.responses import StreamingResponse
    from tests.unit.main.test_request_logging import _make_dummy_db, _make_pipeline

    import logos as main

    registry, websocket = _registry_with_session()
    monkeypatch.setattr(main, "DBManager", _make_dummy_db())
    monkeypatch.setattr(
        main,
        "_context_resolver",
        SimpleNamespace(prepare_headers_and_payload=lambda context, payload: ({}, payload)),
        raising=False,
    )
    monkeypatch.setattr(main, "_logosnode_registry", registry, raising=False)
    pipeline, _completion_calls, _release_calls = _make_pipeline()
    monkeypatch.setattr(main, "_pipeline", pipeline, raising=False)

    response_task = asyncio.ensure_future(
        main._streaming_response(
            SimpleNamespace(
                provider_id=PROVIDER_ID, provider_type="logosnode", lane_id="lane-1", anthropic_dialect=None
            ),
            {"messages": [{"role": "user", "content": "hi"}]},
            42,
            PROVIDER_ID,
            27,
            -1,
            {"policy": "ok"},
            {
                "request_id": "req-splitcomplete",
                "provider_type": "logosnode",
                "queue_depth_at_arrival": 0,
                "utilization_at_arrival": 1,
                "is_cold_start": False,
            },
        )
    )
    await asyncio.wait_for(websocket.stream_command_sent.wait(), timeout=1)
    cmd_id = _sent_stream_cmd_id(websocket)

    role_only_head = (
        b'data: {"id": "chatcmpl-1", "object": "chat.completion.chunk", ' b'"choices": [{"index": 0, "delta": {"ro'
    )
    role_only_tail = b'le": "assistant", "content": ""}}]}\n\n'
    content_frame = (
        b'data: {"id": "chatcmpl-1", "object": "chat.completion.chunk", '
        b'"choices": [{"index": 0, "delta": {"content": "Hello"}}]}\n\n'
    )
    done_frame = b"data: [DONE]\n\n"

    await _feed(registry, cmd_id, {"type": "stream_start", "status_code": 200})
    # The role-only frame arrives split mid-JSON across two chunks.
    await _feed(registry, cmd_id, {"type": "stream_chunk", "chunk": role_only_head})
    await _feed(registry, cmd_id, {"type": "stream_chunk", "chunk": role_only_tail})
    # The first generated content, then a clean end.
    await _feed(registry, cmd_id, {"type": "stream_chunk", "chunk": content_frame})
    await _feed(registry, cmd_id, {"type": "stream_chunk", "chunk": done_frame})
    await _feed(registry, cmd_id, {"type": "stream_end", "success": True})

    response = await asyncio.wait_for(response_task, timeout=2)
    assert isinstance(response, StreamingResponse)
    body = b"".join([part async for part in response.body_iterator])
    await _drain_pending_tasks()

    # The fragment's bytes come back first, in order: the held role-only
    # frame is replayed ahead of the content that committed the 200.
    assert body == role_only_head + role_only_tail + content_frame + done_frame


@pytest.mark.asyncio
async def test_a_legacy_completion_text_chunk_starts_the_stream(monkeypatch):
    """End to end: /v1/completions streams carry the generated output in
    ``choices[].text``, not in a delta. Such a chunk is output — it must
    commit the 200 the moment it arrives, not be buffered until [DONE]
    (which would retain the whole answer in memory and destroy TTFT)."""
    from fastapi.responses import StreamingResponse
    from tests.unit.main.test_request_logging import _make_dummy_db, _make_pipeline

    import logos as main

    registry, websocket = _registry_with_session()
    monkeypatch.setattr(main, "DBManager", _make_dummy_db())
    monkeypatch.setattr(
        main,
        "_context_resolver",
        SimpleNamespace(prepare_headers_and_payload=lambda context, payload: ({}, payload)),
        raising=False,
    )
    monkeypatch.setattr(main, "_logosnode_registry", registry, raising=False)
    pipeline, _completion_calls, _release_calls = _make_pipeline()
    monkeypatch.setattr(main, "_pipeline", pipeline, raising=False)

    response_task = asyncio.ensure_future(
        main._streaming_response(
            SimpleNamespace(
                provider_id=PROVIDER_ID, provider_type="logosnode", lane_id="lane-1", anthropic_dialect=None
            ),
            {"prompt": "Say hello"},
            42,
            PROVIDER_ID,
            27,
            -1,
            {"policy": "ok"},
            {
                "request_id": "req-legacy-completions",
                "provider_type": "logosnode",
                "queue_depth_at_arrival": 0,
                "utilization_at_arrival": 1,
                "is_cold_start": False,
            },
        )
    )
    await asyncio.wait_for(websocket.stream_command_sent.wait(), timeout=1)
    cmd_id = _sent_stream_cmd_id(websocket)

    first = (
        b'data: {"id": "cmpl-1", "object": "text_completion", '
        b'"choices": [{"text": "Hel", "index": 0, "logprobs": null, "finish_reason": null}]}\n\n'
    )
    second = (
        b'data: {"id": "cmpl-1", "object": "text_completion", '
        b'"choices": [{"text": "lo", "index": 0, "logprobs": null, "finish_reason": null}]}\n\n'
    )
    done_frame = b"data: [DONE]\n\n"

    await _feed(registry, cmd_id, {"type": "stream_start", "status_code": 200})
    await _feed(registry, cmd_id, {"type": "stream_chunk", "chunk": first})
    # The response must be back before any further chunk arrives: the first
    # text chunk already committed the stream.
    response = await asyncio.wait_for(response_task, timeout=2)
    assert isinstance(response, StreamingResponse)

    await _feed(registry, cmd_id, {"type": "stream_chunk", "chunk": second})
    await _feed(registry, cmd_id, {"type": "stream_chunk", "chunk": done_frame})
    await _feed(registry, cmd_id, {"type": "stream_end", "success": True})

    body = b"".join([part async for part in response.body_iterator])
    await _drain_pending_tasks()

    assert body == first + second + done_frame


def _native_messages_context() -> SimpleNamespace:
    from logos.anthropic_compat import UpstreamDialect

    return SimpleNamespace(
        provider_id=PROVIDER_ID,
        provider_type="logosnode",
        lane_id="lane-1",
        anthropic_dialect=UpstreamDialect.NATIVE,
        model_name="test-model",
    )


_MESSAGES_START = (
    b"event: message_start\n"
    b'data: {"type": "message_start", "message": {"id": "msg_1", "type": "message", '
    b'"role": "assistant", "content": [], "model": "test-model", "stop_reason": null, '
    b'"usage": {"input_tokens": 10, "output_tokens": 1}}}\n\n'
)
_MESSAGES_BLOCK_START = (
    b"event: content_block_start\n"
    b'data: {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}\n\n'
)


@pytest.mark.asyncio
async def test_a_native_messages_stream_failing_before_content_is_not_a_committed_200(monkeypatch):
    """End to end: a native /v1/messages stream opens with protocol
    metadata (``message_start``, the block announcement) that carries no
    generated output — the native counterpart of the role-only chat delta.
    A worker failure before the first content token must still come back
    as a pre-stream JSON error the internal retry can re-dispatch, not a
    committed 200 stream."""
    from fastapi.responses import JSONResponse, StreamingResponse
    from tests.unit.main.test_request_logging import _make_dummy_db, _make_pipeline

    import logos as main

    registry, websocket = _registry_with_session()
    monkeypatch.setattr(main, "DBManager", _make_dummy_db())
    monkeypatch.setattr(
        main,
        "_context_resolver",
        SimpleNamespace(prepare_headers_and_payload=lambda context, payload: ({}, payload)),
        raising=False,
    )
    monkeypatch.setattr(main, "_logosnode_registry", registry, raising=False)
    # One pre-token attempt: the test pins the buffering, not the same-lane
    # retry that exists for the just-woken race.
    monkeypatch.setattr(main, "_LOGOSNODE_PRETOKEN_RETRIES", 0, raising=False)
    pipeline, _completion_calls, _release_calls = _make_pipeline()
    monkeypatch.setattr(main, "_pipeline", pipeline, raising=False)

    response_task = asyncio.ensure_future(
        main._streaming_response(
            _native_messages_context(),
            {"model": "test-model", "max_tokens": 100, "messages": [{"role": "user", "content": "hi"}]},
            42,
            PROVIDER_ID,
            27,
            -1,
            {"policy": "ok"},
            {
                "request_id": "req-native-messages-fail",
                "provider_type": "logosnode",
                "queue_depth_at_arrival": 0,
                "utilization_at_arrival": 1,
                "is_cold_start": False,
            },
            request_path="/v1/messages",
        )
    )
    await asyncio.wait_for(websocket.stream_command_sent.wait(), timeout=1)
    cmd_id = _sent_stream_cmd_id(websocket)
    await _feed(registry, cmd_id, {"type": "stream_start", "status_code": 200})
    # Only envelope events so far — no generated output yet.
    await _feed(registry, cmd_id, {"type": "stream_chunk", "chunk": _MESSAGES_START})
    await _feed(registry, cmd_id, {"type": "stream_chunk", "chunk": _MESSAGES_BLOCK_START})
    # Worker failure before the first content token.
    await _feed(registry, cmd_id, {"type": "stream_end", "success": False, "error": "lane died"})

    response = await asyncio.wait_for(response_task, timeout=2)
    await _drain_pending_tasks()

    assert not isinstance(
        response, StreamingResponse
    ), "the failure after native Messages metadata was committed as a 200 stream"
    assert isinstance(response, JSONResponse)
    assert response.status_code == 502


@pytest.mark.asyncio
async def test_a_native_responses_stream_failing_before_content_is_not_a_committed_200(monkeypatch):
    """End to end: a native /v1/responses stream opens with
    ``response.created`` / ``response.in_progress`` — neither carries
    generated output. A worker failure before the first content delta must
    still come back as a pre-stream JSON error the internal retry can
    re-dispatch, not a committed 200 stream."""
    from fastapi.responses import JSONResponse, StreamingResponse
    from tests.unit.main.test_request_logging import _make_dummy_db, _make_pipeline

    import logos as main

    registry, websocket = _registry_with_session()
    monkeypatch.setattr(main, "DBManager", _make_dummy_db())
    monkeypatch.setattr(
        main,
        "_context_resolver",
        SimpleNamespace(prepare_headers_and_payload=lambda context, payload: ({}, payload)),
        raising=False,
    )
    monkeypatch.setattr(main, "_logosnode_registry", registry, raising=False)
    # One pre-token attempt: the test pins the buffering, not the same-lane
    # retry that exists for the just-woken race.
    monkeypatch.setattr(main, "_LOGOSNODE_PRETOKEN_RETRIES", 0, raising=False)
    pipeline, _completion_calls, _release_calls = _make_pipeline()
    monkeypatch.setattr(main, "_pipeline", pipeline, raising=False)

    response_task = asyncio.ensure_future(
        main._streaming_response(
            _native_messages_context(),
            {"model": "test-model", "max_output_tokens": 100, "input": "hi"},
            42,
            PROVIDER_ID,
            27,
            -1,
            {"policy": "ok"},
            {
                "request_id": "req-native-responses-fail",
                "provider_type": "logosnode",
                "queue_depth_at_arrival": 0,
                "utilization_at_arrival": 1,
                "is_cold_start": False,
            },
            request_path="/v1/responses",
        )
    )
    await asyncio.wait_for(websocket.stream_command_sent.wait(), timeout=1)
    cmd_id = _sent_stream_cmd_id(websocket)
    await _feed(registry, cmd_id, {"type": "stream_start", "status_code": 200})
    await _feed(
        registry,
        cmd_id,
        {
            "type": "stream_chunk",
            "chunk": (
                b"event: response.created\n"
                b'data: {"type": "response.created", "response": {"id": "resp_1", '
                b'"status": "in_progress", "model": "test-model", "output": []}}\n\n'
            ),
        },
    )
    await _feed(
        registry,
        cmd_id,
        {
            "type": "stream_chunk",
            "chunk": (
                b"event: response.in_progress\n"
                b'data: {"type": "response.in_progress", "response": {"id": "resp_1", "status": "in_progress"}}\n\n'
            ),
        },
    )
    # Worker failure before the first content delta.
    await _feed(registry, cmd_id, {"type": "stream_end", "success": False, "error": "lane died"})

    response = await asyncio.wait_for(response_task, timeout=2)
    await _drain_pending_tasks()

    assert not isinstance(
        response, StreamingResponse
    ), "the failure after Responses metadata was committed as a 200 stream"
    assert isinstance(response, JSONResponse)
    assert response.status_code == 502


@pytest.mark.asyncio
async def test_a_native_messages_mid_stream_failure_emits_an_anthropic_error_event(monkeypatch):
    """End to end: when a native /v1/messages stream fails after content and
    no resume is available, the fallback frame must be one the client can
    parse — an Anthropic ``event: error`` frame, not the OpenAI error data
    frame plus ``[DONE]``, which are protocol noise to a Messages client."""
    from fastapi.responses import StreamingResponse
    from tests.unit.main.test_request_logging import _make_dummy_db, _make_pipeline

    import logos as main

    registry, websocket = _registry_with_session()
    monkeypatch.setattr(main, "DBManager", _make_dummy_db())
    monkeypatch.setattr(
        main,
        "_context_resolver",
        SimpleNamespace(prepare_headers_and_payload=lambda context, payload: ({}, payload)),
        raising=False,
    )
    monkeypatch.setattr(main, "_logosnode_registry", registry, raising=False)
    pipeline, _completion_calls, _release_calls = _make_pipeline()
    monkeypatch.setattr(main, "_pipeline", pipeline, raising=False)

    response_task = asyncio.ensure_future(
        main._streaming_response(
            _native_messages_context(),
            {"model": "test-model", "max_tokens": 100, "messages": [{"role": "user", "content": "hi"}]},
            42,
            PROVIDER_ID,
            27,
            -1,
            {"policy": "ok"},
            {
                "request_id": "req-native-messages-midfail",
                "provider_type": "logosnode",
                "queue_depth_at_arrival": 0,
                "utilization_at_arrival": 1,
                "is_cold_start": False,
            },
            request_path="/v1/messages",
        )
    )
    await asyncio.wait_for(websocket.stream_command_sent.wait(), timeout=1)
    cmd_id = _sent_stream_cmd_id(websocket)
    await _feed(registry, cmd_id, {"type": "stream_start", "status_code": 200})
    # Envelope metadata (held), then the first content token (commits the 200).
    await _feed(registry, cmd_id, {"type": "stream_chunk", "chunk": _MESSAGES_START})
    await _feed(registry, cmd_id, {"type": "stream_chunk", "chunk": _MESSAGES_BLOCK_START})
    delta = (
        b"event: content_block_delta\n"
        b'data: {"type": "content_block_delta", "index": 0, '
        b'"delta": {"type": "text_delta", "text": "Hi"}}\n\n'
    )
    await _feed(registry, cmd_id, {"type": "stream_chunk", "chunk": delta})
    # Worker failure mid-stream; no resume is available in this setup, so
    # the fallback error frame is what the client receives.
    await _feed(registry, cmd_id, {"type": "stream_end", "success": False, "error": "lane died"})

    response = await asyncio.wait_for(response_task, timeout=2)
    assert isinstance(response, StreamingResponse)
    body = b"".join([part async for part in response.body_iterator])
    await _drain_pending_tasks()

    # The held envelope is replayed ahead of the content, then the failure
    # arrives as an Anthropic error event — and nothing after it.
    assert body == (
        _MESSAGES_START + _MESSAGES_BLOCK_START + delta + b"\n\n" + b"event: error\n"
        b'data: {"type": "error", "error": {"type": "api_error", "message": "lane died"}}\n\n'
    )
    assert b"[DONE]" not in body


@pytest.mark.asyncio
async def test_a_native_messages_mid_stream_failure_is_not_resumed(monkeypatch):
    """End to end: the stream has everything the resume guard otherwise
    needs — a plain-text prefix (``Hi``), a budget with attempts left,
    eligible deployments, and a ``message_start`` whose provisional
    ``output_tokens`` lets the continuation budget be computed. But the
    continuation contract is a Chat Completions one: resuming would send
    OpenAI-only fields to a lane serving /v1/messages and splice a second
    ``message_start`` into the client's stream. The guard must block on the
    request path, and the failure stays on the Anthropic error fallback."""
    from fastapi.responses import StreamingResponse
    from tests.unit.main.test_request_logging import _make_dummy_db, _make_pipeline

    import logos as main

    registry, websocket = _registry_with_session()
    monkeypatch.setattr(main, "DBManager", _make_dummy_db())
    monkeypatch.setattr(
        main,
        "_context_resolver",
        SimpleNamespace(prepare_headers_and_payload=lambda context, payload: ({}, payload)),
        raising=False,
    )
    monkeypatch.setattr(main, "_logosnode_registry", registry, raising=False)
    pipeline, _completion_calls, _release_calls = _make_pipeline()
    process_calls = []

    async def fake_process(request):  # noqa: ARG001
        process_calls.append(request)
        return SimpleNamespace(
            success=True,
            error=None,
            model_id=27,
            provider_id=2,
            execution_context=SimpleNamespace(
                model_id=27, provider_id=2, provider_type="logosnode", lane_id="lane-2", engine="vllm"
            ),
            classification_stats={},
            scheduling_stats={"request_id": "req-1"},
        )

    pipeline.process = fake_process
    monkeypatch.setattr(main, "_pipeline", pipeline, raising=False)

    response_task = asyncio.ensure_future(
        main._streaming_response(
            _native_messages_context(),
            {"model": "test-model", "max_tokens": 100, "messages": [{"role": "user", "content": "hi"}]},
            42,
            PROVIDER_ID,
            27,
            -1,
            {"policy": "ok"},
            {
                "request_id": "req-native-messages-noresume",
                "provider_type": "logosnode",
                "queue_depth_at_arrival": 0,
                "utilization_at_arrival": 1,
                "is_cold_start": False,
            },
            request_path="/v1/messages",
            deployments=[
                {"model_id": 27, "provider_id": PROVIDER_ID, "type": "logosnode"},
                {"model_id": 27, "provider_id": 2, "type": "logosnode"},
            ],
            # A real-clock budget: the stream is opened with its deadline,
            # which must stay in the future in real monotonic time.
            retry_budget=main.RetryBudget(max_attempts=3, deadline_s=100.0),
        )
    )
    await asyncio.wait_for(websocket.stream_command_sent.wait(), timeout=1)
    cmd_id = _sent_stream_cmd_id(websocket)
    await _feed(registry, cmd_id, {"type": "stream_start", "status_code": 200})
    # Envelope metadata (held, with the provisional output count), then the
    # first content token (commits the 200), then the failure.
    await _feed(registry, cmd_id, {"type": "stream_chunk", "chunk": _MESSAGES_START})
    await _feed(registry, cmd_id, {"type": "stream_chunk", "chunk": _MESSAGES_BLOCK_START})
    delta = (
        b"event: content_block_delta\n"
        b'data: {"type": "content_block_delta", "index": 0, '
        b'"delta": {"type": "text_delta", "text": "Hi"}}\n\n'
    )
    await _feed(registry, cmd_id, {"type": "stream_chunk", "chunk": delta})
    await _feed(registry, cmd_id, {"type": "stream_end", "success": False, "error": "lane died"})

    response = await asyncio.wait_for(response_task, timeout=2)
    assert isinstance(response, StreamingResponse)
    body = b"".join([part async for part in response.body_iterator])
    await _drain_pending_tasks()

    # No takeover was scheduled — the guard blocked on the request path —
    # and the client's stream ends in the Anthropic error event.
    assert process_calls == []
    assert body.endswith(
        b"event: error\n" b'data: {"type": "error", "error": {"type": "api_error", "message": "lane died"}}\n\n'
    )
    assert b"[DONE]" not in body


# ---------------------------------------------------------------------------
# The slot handoff when a takeover is scheduled
#
# A resumed stream runs under the SAME request ID as the failed attempt, and
# the facade keys its active ledger by that ID. The failed node's scheduler
# slot must therefore be released *before* the takeover's scheduling is
# awaited: the resume may need exactly the capacity that slot still holds
# (a single-node model waiting on itself until the queue times out), and a
# release that lands after the takeover registered under the same ID would
# pop the takeover's ledger row, leak the peer's active count, and make its
# final release a swallowed KeyError.
#
# Both scenarios run on the real scheduler and facade — a fake pipeline that
# records releases would pass whatever order the streamer picks.
# ---------------------------------------------------------------------------

_RESUME_MODEL_ID = 27
_RESUME_MODEL_NAME = "resume-model"
_FAILED_PROVIDER_ID = 9


def _deployment(provider_id: int) -> dict:
    return {"model_id": _RESUME_MODEL_ID, "provider_id": provider_id, "type": "logosnode"}


def _resume_lane() -> dict:
    """One ready vLLM lane per provider. The orchestrator's local ledger
    (one slot, from the provider config) is the admission gate; the engine
    signals report an idle lane, which is what the worker shows once the
    failed generation is gone."""
    return {
        "lane_id": "resume-lane",
        "model": _RESUME_MODEL_NAME,
        "runtime_state": "loaded",
        "vllm": True,
        "num_parallel": 10,
        "backend_metrics": {"queue_waiting": 0, "requests_running": 0},
        "loaded_models": [{"name": _RESUME_MODEL_NAME}],
    }


def _resume_context(model_id: int, provider_id: int) -> SimpleNamespace:
    return SimpleNamespace(
        model_id=model_id,
        provider_id=provider_id,
        provider_type="logosnode",
        lane_id=f"lane-{provider_id}",
        model_name=_RESUME_MODEL_NAME,
        engine="vllm",
        forward_url=f"http://fake/{provider_id}",
    )


class _ResumeCtxResolver:
    """The pipeline's context resolver for the scenario: every
    (model, provider) resolves to that provider's vLLM lane."""

    async def resolve_context(self, *, model_id: int, provider_id: int, request_path: str | None = None):
        return _resume_context(model_id, provider_id)


class _ResumeMonitoring:
    """No-op monitoring: the scenario exercises scheduling, not metrics."""

    def __getattr__(self, name):  # noqa: ARG002
        def _no_op(*args, **kwargs):
            return None

        return _no_op


def _resume_env(monkeypatch, *, provider_ids: tuple[int, ...]):
    """Real pipeline + FCFS scheduler + facade behind the streamer.

    Every deployment is a single-slot logosnode lane, so the scheduler's
    local ledger is the only gate: a resume can only be placed once the
    failed attempt's slot has been handed back.
    """
    from unittest.mock import MagicMock

    from tests.unit.main.test_request_logging import _make_dummy_db

    import logos as main
    from logos.pipeline.fcfs_scheduler import FcfScheduler
    from logos.pipeline.pipeline import RequestPipeline
    from logos.queue import PriorityQueueManager
    from logos.sdi.logosnode_facade import LogosNodeSchedulingDataFacade

    class _SnapshotRegistry:
        @staticmethod
        def peek_runtime_snapshot(provider_id: int):  # noqa: ARG004
            return {"runtime": {"lanes": [_resume_lane()]}}

        @staticmethod
        def is_provider_online(provider_id: int) -> bool:  # noqa: ARG004
            return True

    monkeypatch.setattr(
        "logos.sdi.providers.logosnode_provider.LogosNodeDataProvider._load_provider_config",
        lambda self: {"parallel_capacity": 1},
    )
    monkeypatch.setattr(
        "logos.sdi.providers.logosnode_provider.LogosNodeDataProvider._fetch_ps_data",
        lambda self: {"models": []},
    )

    queue_manager = PriorityQueueManager()
    facade = LogosNodeSchedulingDataFacade(queue_manager, runtime_registry=_SnapshotRegistry())
    for provider_id in provider_ids:
        facade.register_model(
            _RESUME_MODEL_ID,
            "logosnode",
            "http://fake",
            _RESUME_MODEL_NAME,
            65536,
            provider_id=provider_id,
        )

    scheduler = FcfScheduler(
        queue_manager=queue_manager,
        logosnode_facade=facade,
        azure_facade=MagicMock(),
    )
    scheduler.update_model_registry({(_RESUME_MODEL_ID, p): "logosnode" for p in provider_ids})
    pipeline = RequestPipeline(
        classifier=object(),
        scheduler=scheduler,
        executor=object(),
        context_resolver=_ResumeCtxResolver(),
        monitoring=_ResumeMonitoring(),
    )

    registry = LogosNodeRuntimeRegistry()
    websockets: dict[int, _FakeWebSocket] = {}
    for provider_id in provider_ids:
        websocket = _FakeWebSocket(provider_id=provider_id)
        websocket.bind(registry)
        registry._sessions[provider_id] = ProviderSession(
            provider_id=provider_id,
            worker_id=f"worker-{provider_id}",
            websocket=websocket,
            actions={CANCEL_COMMAND_ACTION},
        )
        websockets[provider_id] = websocket

    monkeypatch.setattr(main, "DBManager", _make_dummy_db())
    monkeypatch.setattr(
        main,
        "_context_resolver",
        SimpleNamespace(prepare_headers_and_payload=lambda context, payload: ({}, payload)),
        raising=False,
    )
    monkeypatch.setattr(main, "_logosnode_registry", registry, raising=False)
    monkeypatch.setattr(main, "_pipeline", pipeline, raising=False)

    return registry, websockets, facade, pipeline


async def _dispatch_initial(pipeline, provider_ids: tuple[int, ...], request_id: str):
    """The request's first hop: a dispatch that reserves the first node's
    single slot through the real scheduler. Pinned, so the scenario does not
    also stand up a classifier — the reservation path is the same."""
    from logos.pipeline.pipeline import PipelineRequest

    result = await pipeline.process(
        PipelineRequest(
            payload={"messages": [{"role": "user", "content": "hi"}]},
            headers={},
            allowed_models=[_RESUME_MODEL_ID],
            deployments=[_deployment(p) for p in provider_ids],
            request_id=request_id,
            pinned_model_id=_RESUME_MODEL_ID,
            request_path="v1/chat/completions",
        )
    )
    assert result.success
    return result.execution_context


def _stream_cmd_ids(websocket: _FakeWebSocket) -> list[str]:
    return [m["cmd_id"] for m in websocket.sent if m.get("action") == "infer_stream"]


async def _wait_for_stream_cmd_count(websocket: _FakeWebSocket, count: int, timeout: float = 2.0) -> None:
    """Block until ``count`` stream commands are on the wire. The takeover's
    scheduling is what the wait is for — a resume that hangs behind the
    failed slot's capacity never sends its second command."""

    async def _poll() -> None:
        while len(_stream_cmd_ids(websocket)) < count:
            await asyncio.sleep(0.01)

    await asyncio.wait_for(_poll(), timeout=timeout)


async def _feed_pid(registry: LogosNodeRuntimeRegistry, provider_id: int, cmd_id: str, event: dict) -> None:
    queue = registry._sessions[provider_id].pending_streams[cmd_id]
    await queue.put(event)


async def _fail_the_stream_mid_answer(
    registry: LogosNodeRuntimeRegistry, provider_id: int, websocket: _FakeWebSocket, response, first_frame: bytes
):
    """Consume the committed first chunk, fail the lane, and hand back the
    pending read — the resume logic runs inside it — plus the body to keep
    draining."""
    body = response.body_iterator
    assert await body.__anext__() == first_frame
    consumer = asyncio.ensure_future(body.__anext__())
    await _feed_pid(
        registry,
        provider_id,
        _sent_stream_cmd_id(websocket),
        {"type": "stream_end", "success": False, "error": "lane died"},
    )
    return consumer, body


def _chat_frame(content: str) -> bytes:
    return (
        b'data: {"id": "chatcmpl-1", "object": "chat.completion.chunk", '
        b'"choices": [{"index": 0, "delta": {"content": "%s"}}]}\n\n' % content.encode()
    )


@pytest.mark.asyncio
async def test_a_resumed_stream_releases_the_failed_slot_before_its_takeover(monkeypatch):
    """End to end with the real scheduler and facade, two single-slot nodes:
    the failed node's slot must be released before the takeover is
    scheduled. The resume runs under the same request ID, and the facade
    keys its active ledger by that ID — a release that lands after the
    takeover registered would pop the takeover's row, leak the peer's active
    count, and leave the peer's final release as a swallowed KeyError. Both
    providers' ledgers must end clean."""
    from fastapi.responses import StreamingResponse

    import logos as main

    registry, websockets, facade, pipeline = _resume_env(monkeypatch, provider_ids=(_FAILED_PROVIDER_ID, PROVIDER_ID))
    failed_ws = websockets[_FAILED_PROVIDER_ID]
    peer_ws = websockets[PROVIDER_ID]

    ctx = await _dispatch_initial(pipeline, (_FAILED_PROVIDER_ID, PROVIDER_ID), "req-slot-handoff")
    assert ctx.provider_id == _FAILED_PROVIDER_ID
    # The scenario is live: the failed node holds the model's only slot on
    # itself, and the peer is free.
    assert facade._providers[_FAILED_PROVIDER_ID].get_active_count(_RESUME_MODEL_ID) == 1
    assert facade._providers[PROVIDER_ID].get_active_count(_RESUME_MODEL_ID) == 0

    first_frame = _chat_frame("Hello")
    response_task = asyncio.ensure_future(
        main._streaming_response(
            ctx,
            {"messages": [{"role": "user", "content": "hi"}]},
            42,
            _FAILED_PROVIDER_ID,
            _RESUME_MODEL_ID,
            -1,
            {"policy": "ok"},
            {
                "request_id": "req-slot-handoff",
                "provider_type": "logosnode",
                "queue_depth_at_arrival": 0,
                "utilization_at_arrival": 0,
                "is_cold_start": False,
            },
            request_path="v1/chat/completions",
            deployments=[_deployment(_FAILED_PROVIDER_ID), _deployment(PROVIDER_ID)],
            # A real-clock budget: the stream is opened with its deadline,
            # which must stay in the future in real monotonic time.
            retry_budget=main.RetryBudget(max_attempts=3, deadline_s=100.0),
        )
    )
    await asyncio.wait_for(failed_ws.stream_command_sent.wait(), timeout=1)
    await _feed_pid(
        registry, _FAILED_PROVIDER_ID, _sent_stream_cmd_id(failed_ws), {"type": "stream_start", "status_code": 200}
    )
    await _feed_pid(
        registry, _FAILED_PROVIDER_ID, _sent_stream_cmd_id(failed_ws), {"type": "stream_chunk", "chunk": first_frame}
    )

    response = await asyncio.wait_for(response_task, timeout=2)
    assert isinstance(response, StreamingResponse)

    consumer, body = await _fail_the_stream_mid_answer(registry, _FAILED_PROVIDER_ID, failed_ws, response, first_frame)
    try:
        # The takeover is scheduled on the peer while the read above is
        # pending — wait for its stream command, then deliver the
        # continuation.
        await _wait_for_stream_cmd_count(peer_ws, 1, timeout=2)
        takeover_cmd = _stream_cmd_ids(peer_ws)[0]
        resumed_frame = _chat_frame(" there")
        done_frame = b"data: [DONE]\n\n"
        await _feed_pid(registry, PROVIDER_ID, takeover_cmd, {"type": "stream_start", "status_code": 200})
        await _feed_pid(registry, PROVIDER_ID, takeover_cmd, {"type": "stream_chunk", "chunk": resumed_frame})
        await _feed_pid(registry, PROVIDER_ID, takeover_cmd, {"type": "stream_chunk", "chunk": done_frame})
        await _feed_pid(registry, PROVIDER_ID, takeover_cmd, {"type": "stream_end", "success": True})

        assert await asyncio.wait_for(consumer, timeout=2) == resumed_frame
        assert [chunk async for chunk in body] == [done_frame]

        # The takeover ran on the peer's lane as a continuation of the
        # partial answer — a resume, not a restart.
        takeover = next(m["params"] for m in peer_ws.sent if m.get("action") == "infer_stream")
        assert takeover["lane_id"] == f"lane-{PROVIDER_ID}"
        assert takeover["payload"]["messages"][-1] == {"role": "assistant", "content": "Hello"}
        assert takeover["payload"]["continue_final_message"] is True
        assert takeover["payload"]["add_generation_prompt"] is False
        assert len(_stream_cmd_ids(failed_ws)) == 1
    finally:
        if not consumer.done():
            consumer.cancel()
        await _drain_pending_tasks()

    # The failed node's slot went back before the takeover was scheduled,
    # and the takeover's slot with it at the end: both providers' ledgers
    # are clean, and the request is tracked nowhere.
    assert facade._providers[_FAILED_PROVIDER_ID].get_active_count(_RESUME_MODEL_ID) == 0
    assert facade._providers[PROVIDER_ID].get_active_count(_RESUME_MODEL_ID) == 0
    assert facade._providers[_FAILED_PROVIDER_ID]._active_request_ids == {}
    assert facade._providers[PROVIDER_ID]._active_request_ids == {}
    assert facade._request_tracking == {}


@pytest.mark.asyncio
async def test_a_resumed_stream_on_the_only_node_gets_the_slot_the_failure_held(monkeypatch):
    """The single-node case: the resume's only eligible deployment is the
    one that just failed, and it holds the model's single slot. The failed
    slot must be released before the takeover's scheduling awaits —
    otherwise the resume waits in the queue for capacity it is holding
    itself, until the (minutes-long) queue timeout."""
    from fastapi.responses import StreamingResponse

    import logos as main

    registry, websockets, facade, pipeline = _resume_env(monkeypatch, provider_ids=(PROVIDER_ID,))
    websocket = websockets[PROVIDER_ID]

    ctx = await _dispatch_initial(pipeline, (PROVIDER_ID,), "req-single-slot")
    assert ctx.provider_id == PROVIDER_ID
    # The scenario is live: the failed node holds the model's only slot.
    assert facade._providers[PROVIDER_ID].get_active_count(_RESUME_MODEL_ID) == 1

    first_frame = _chat_frame("Hello")
    response_task = asyncio.ensure_future(
        main._streaming_response(
            ctx,
            {"messages": [{"role": "user", "content": "hi"}]},
            42,
            PROVIDER_ID,
            _RESUME_MODEL_ID,
            -1,
            {"policy": "ok"},
            {
                "request_id": "req-single-slot",
                "provider_type": "logosnode",
                "queue_depth_at_arrival": 0,
                "utilization_at_arrival": 0,
                "is_cold_start": False,
            },
            request_path="v1/chat/completions",
            deployments=[_deployment(PROVIDER_ID)],
            # A real-clock budget: the stream is opened with its deadline,
            # which must stay in the future in real monotonic time.
            retry_budget=main.RetryBudget(max_attempts=3, deadline_s=100.0),
        )
    )
    await asyncio.wait_for(websocket.stream_command_sent.wait(), timeout=1)
    await _feed_pid(registry, PROVIDER_ID, _sent_stream_cmd_id(websocket), {"type": "stream_start", "status_code": 200})
    await _feed_pid(
        registry, PROVIDER_ID, _sent_stream_cmd_id(websocket), {"type": "stream_chunk", "chunk": first_frame}
    )

    response = await asyncio.wait_for(response_task, timeout=2)
    assert isinstance(response, StreamingResponse)

    consumer, body = await _fail_the_stream_mid_answer(registry, PROVIDER_ID, websocket, response, first_frame)
    try:
        # The same node takes over: its single slot had to be free by the
        # time the resume scheduled, or the wait below never ends.
        await _wait_for_stream_cmd_count(websocket, 2, timeout=2)
        takeover_cmd = _stream_cmd_ids(websocket)[1]
        resumed_frame = _chat_frame(" there")
        done_frame = b"data: [DONE]\n\n"
        await _feed_pid(registry, PROVIDER_ID, takeover_cmd, {"type": "stream_start", "status_code": 200})
        await _feed_pid(registry, PROVIDER_ID, takeover_cmd, {"type": "stream_chunk", "chunk": resumed_frame})
        await _feed_pid(registry, PROVIDER_ID, takeover_cmd, {"type": "stream_chunk", "chunk": done_frame})
        await _feed_pid(registry, PROVIDER_ID, takeover_cmd, {"type": "stream_end", "success": True})

        assert await asyncio.wait_for(consumer, timeout=2) == resumed_frame
        assert [chunk async for chunk in body] == [done_frame]
    finally:
        if not consumer.done():
            consumer.cancel()
        await _drain_pending_tasks()

    # The slot the failure held is back, and the takeover's with it.
    assert facade._providers[PROVIDER_ID].get_active_count(_RESUME_MODEL_ID) == 0
    assert facade._providers[PROVIDER_ID]._active_request_ids == {}
    assert facade._request_tracking == {}


def _responses_context() -> SimpleNamespace:
    """The real /v1/responses context: the resolver sets ``anthropic_dialect``
    only for Messages requests, so a Responses stream has no dialect marker —
    the failure branch must decide from the request path."""
    return SimpleNamespace(
        provider_id=PROVIDER_ID,
        provider_type="logosnode",
        lane_id="lane-1",
        anthropic_dialect=None,
        model_name="test-model",
    )


_RESPONSES_CREATED = (
    b"event: response.created\n"
    b'data: {"type": "response.created", "sequence_number": 0, "response": {"id": "resp_1", '
    b'"status": "in_progress", "model": "test-model", "output": []}}\n\n'
)
_RESPONSES_DELTA = (
    b"event: response.output_text.delta\n"
    b'data: {"type": "response.output_text.delta", "sequence_number": 1, "item_id": "item_1", '
    b'"output_index": 0, "content_index": 0, "delta": "Hi"}\n\n'
)


@pytest.mark.asyncio
async def test_a_responses_mid_stream_failure_emits_a_responses_failed_event(monkeypatch):
    """End to end: when a /v1/responses stream fails after content and no
    resume is available, the fallback frame must be the Responses terminal
    failure — a ``response.failed`` event, not the chat-completions error
    data frame plus ``[DONE]``, which a Responses client does not recognise
    as its terminal failure protocol. The event carries the full response
    envelope the stream announced in ``response.created`` under the next
    sequence number. The context is the real one:
    ``anthropic_dialect=None``."""
    from fastapi.responses import StreamingResponse
    from tests.unit.main.test_request_logging import _make_dummy_db, _make_pipeline

    import logos as main

    registry, websocket = _registry_with_session()
    monkeypatch.setattr(main, "DBManager", _make_dummy_db())
    monkeypatch.setattr(
        main,
        "_context_resolver",
        SimpleNamespace(prepare_headers_and_payload=lambda context, payload: ({}, payload)),
        raising=False,
    )
    monkeypatch.setattr(main, "_logosnode_registry", registry, raising=False)
    pipeline, _completion_calls, _release_calls = _make_pipeline()
    monkeypatch.setattr(main, "_pipeline", pipeline, raising=False)

    response_task = asyncio.ensure_future(
        main._streaming_response(
            _responses_context(),
            {"model": "test-model", "max_output_tokens": 100, "input": "hi"},
            42,
            PROVIDER_ID,
            27,
            -1,
            {"policy": "ok"},
            {
                "request_id": "req-responses-midfail",
                "provider_type": "logosnode",
                "queue_depth_at_arrival": 0,
                "utilization_at_arrival": 1,
                "is_cold_start": False,
            },
            request_path="/v1/responses",
        )
    )
    await asyncio.wait_for(websocket.stream_command_sent.wait(), timeout=1)
    cmd_id = _sent_stream_cmd_id(websocket)
    await _feed(registry, cmd_id, {"type": "stream_start", "status_code": 200})
    # Envelope metadata (held), then the first content delta (commits the 200).
    await _feed(registry, cmd_id, {"type": "stream_chunk", "chunk": _RESPONSES_CREATED})
    await _feed(registry, cmd_id, {"type": "stream_chunk", "chunk": _RESPONSES_DELTA})
    # Worker failure mid-stream; no resume is available in this setup, so
    # the fallback error frame is what the client receives.
    await _feed(registry, cmd_id, {"type": "stream_end", "success": False, "error": "lane died"})

    response = await asyncio.wait_for(response_task, timeout=2)
    assert isinstance(response, StreamingResponse)
    body = b"".join([part async for part in response.body_iterator])
    await _drain_pending_tasks()

    # The held envelope is replayed ahead of the content, then the failure
    # arrives as the Responses terminal event: the announced response
    # envelope with its status flipped, the error attached, and the next
    # sequence number — and nothing after it.
    assert body == (
        _RESPONSES_CREATED + _RESPONSES_DELTA + b"\n\n" + b"event: response.failed\n"
        b'data: {"type": "response.failed", "response": {"id": "resp_1", "status": "failed", '
        b'"model": "test-model", "output": [], "error": {"code": "server_error", '
        b'"message": "lane died"}}, "sequence_number": 2}\n\n'
    )
    assert b"[DONE]" not in body


# ---------------------------------------------------------------------------
# Non-streaming path — same exposure, same fix
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_abandoned_sync_infer_is_cancelled_on_the_worker():
    registry, websocket = _registry_with_session()

    call = asyncio.ensure_future(registry.send_command(PROVIDER_ID, "infer", {"lane_id": "lane-a"}))
    await asyncio.wait_for(websocket.infer_command_sent.wait(), timeout=1)
    cmd_id = next(m["cmd_id"] for m in websocket.sent if m.get("action") == "infer")

    call.cancel()
    with pytest.raises(asyncio.CancelledError):
        await call
    await _drain_pending_tasks()

    frames = websocket.cancel_frames()
    assert len(frames) == 1
    assert frames[0]["params"] == {"target_cmd_id": cmd_id}
    assert cmd_id not in registry._sessions[PROVIDER_ID].pending_commands


@pytest.mark.asyncio
async def test_a_cancelled_cancel_does_not_cancel_itself():
    """Guard against the obvious recursion."""
    registry, websocket = _registry_with_session()
    websocket.auto_ack = False  # leave the cancel RPC hanging

    call = asyncio.ensure_future(
        registry.send_command(PROVIDER_ID, CANCEL_COMMAND_ACTION, {"target_cmd_id": "whatever"})
    )
    await asyncio.sleep(0)
    call.cancel()
    with pytest.raises(asyncio.CancelledError):
        await call
    await _drain_pending_tasks()

    # Exactly the one cancel we sent ourselves — no follow-up for it.
    assert len(websocket.cancel_frames()) == 1


# ---------------------------------------------------------------------------
# Capability negotiation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hello_records_the_actions_a_worker_supports():
    registry, _websocket = _registry_with_session(actions=set())

    await registry.on_hello(
        provider_id=PROVIDER_ID,
        worker_id="worker-a",
        actions=["infer", "infer_stream", CANCEL_COMMAND_ACTION],
    )

    assert CANCEL_COMMAND_ACTION in registry._sessions[PROVIDER_ID].actions


@pytest.mark.asyncio
async def test_hello_without_actions_leaves_the_known_set_intact():
    """A worker that sends no action list must not silently lose the
    capability it advertised on a previous hello."""
    registry, _websocket = _registry_with_session()

    await registry.on_hello(provider_id=PROVIDER_ID, worker_id="worker-a")

    assert CANCEL_COMMAND_ACTION in registry._sessions[PROVIDER_ID].actions


# ---------------------------------------------------------------------------
# The response path must close the worker stream deterministically
#
# `send_stream_command`'s cleanup is what sends the cancellation, so it has to
# run while the disconnect is being handled. A bare `async for` over the inner
# generator would leave that to the async-generator GC hook — cleanup at some
# unspecified later tick, which for an abort is the same as not having one.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_closing_the_response_closes_the_worker_stream_at_once(monkeypatch):
    from tests.unit.main.test_request_logging import _make_dummy_db, _make_pipeline

    import logos as main

    closed = asyncio.Event()

    async def fake_send_stream_command(**kwargs):  # noqa: ARG001
        try:
            yield b'data: {"id":"c1","choices":[{"delta":{"content":"hi"}}]}\n\n'
            yield b'data: {"id":"c2","choices":[{"delta":{"content":" there"}}]}\n\n'
        finally:
            # Stands in for the real cleanup, which sends `cancel_command`.
            closed.set()

    monkeypatch.setattr(main, "DBManager", _make_dummy_db())
    monkeypatch.setattr(
        main,
        "_context_resolver",
        SimpleNamespace(prepare_headers_and_payload=lambda context, payload: ({}, payload)),
        raising=False,
    )
    monkeypatch.setattr(
        main,
        "_logosnode_registry",
        SimpleNamespace(send_stream_command=fake_send_stream_command),
        raising=False,
    )
    pipeline, _completion_calls, _release_calls = _make_pipeline()
    monkeypatch.setattr(main, "_pipeline", pipeline, raising=False)

    response = await main._streaming_response(
        SimpleNamespace(provider_id=12, provider_type="logosnode", lane_id="lane-1", anthropic_dialect=None),
        {"messages": [{"role": "user", "content": "hi"}]},
        42,
        12,
        27,
        -1,
        {"policy": "ok"},
        {
            "request_id": "req-abandoned",
            "provider_type": "logosnode",
            "queue_depth_at_arrival": 0,
            "utilization_at_arrival": 1,
            "is_cold_start": False,
        },
    )

    body = response.body_iterator
    await body.__anext__()  # one chunk delivered, then the client vanishes
    assert not closed.is_set()

    await body.aclose()

    # No sleep, no gc pass: the worker stream must already be closed by the
    # time the disconnect handler returns.
    assert closed.is_set(), "worker stream cleanup was deferred to the GC hook"


@pytest.mark.asyncio
async def test_an_abandoned_response_reaches_the_worker_as_a_cancellation(monkeypatch):
    """The whole chain, with the real registry behind the response: client
    goes away → response iterator closed → worker told to abort."""
    from tests.unit.main.test_request_logging import _make_dummy_db, _make_pipeline

    import logos as main

    registry, websocket = _registry_with_session()

    monkeypatch.setattr(main, "DBManager", _make_dummy_db())
    monkeypatch.setattr(
        main,
        "_context_resolver",
        SimpleNamespace(prepare_headers_and_payload=lambda context, payload: ({}, payload)),
        raising=False,
    )
    monkeypatch.setattr(main, "_logosnode_registry", registry, raising=False)
    pipeline, _completion_calls, _release_calls = _make_pipeline()
    monkeypatch.setattr(main, "_pipeline", pipeline, raising=False)

    # The first chunk is pulled before the response is committed (#815), so
    # the stream command goes out as soon as the call starts — the worker
    # frame has to be fed while the call is in flight, not after it returns.
    response_task = asyncio.ensure_future(
        main._streaming_response(
            SimpleNamespace(
                provider_id=PROVIDER_ID,
                provider_type="logosnode",
                lane_id="lane-1",
                anthropic_dialect=None,
            ),
            {"messages": [{"role": "user", "content": "hi"}]},
            42,
            PROVIDER_ID,
            27,
            -1,
            {"policy": "ok"},
            {
                "request_id": "req-abandoned",
                "provider_type": "logosnode",
                "queue_depth_at_arrival": 0,
                "utilization_at_arrival": 1,
                "is_cold_start": False,
            },
        )
    )
    await asyncio.wait_for(websocket.stream_command_sent.wait(), timeout=1)
    cmd_id = _sent_stream_cmd_id(websocket)
    await _feed(registry, cmd_id, {"type": "stream_chunk", "chunk": b"data: {}\n\n"})
    response = await response_task

    body = response.body_iterator
    await body.__anext__()  # the pre-pulled first chunk

    await body.aclose()
    await _drain_pending_tasks()

    frames = websocket.cancel_frames()
    assert len(frames) == 1, "the worker was never told the request was abandoned"
    assert frames[0]["params"] == {"target_cmd_id": cmd_id}


# ---------------------------------------------------------------------------
# Observability — the counter is how the fix is verified in production
# ---------------------------------------------------------------------------


def _cancellation_counts() -> dict[str, float]:
    from logos.monitoring import prometheus_metrics as prom

    counts: dict[str, float] = {}
    for metric in prom.registry.collect():
        if metric.name != "logos_worker_cancellations":
            continue
        for sample in metric.samples:
            if sample.name.endswith("_total"):
                counts[sample.labels["result"]] = sample.value
    return counts


def _delta(before: dict[str, float], after: dict[str, float], label: str) -> float:
    return after.get(label, 0.0) - before.get(label, 0.0)


@pytest.mark.asyncio
async def test_an_aborted_generation_is_counted():
    registry, websocket = _registry_with_session()
    before = _cancellation_counts()

    stream = registry.send_stream_command(PROVIDER_ID, "infer_stream", {"lane_id": "lane-a"})
    consumer = asyncio.ensure_future(stream.__anext__())
    await asyncio.wait_for(websocket.stream_command_sent.wait(), timeout=1)
    cmd_id = _sent_stream_cmd_id(websocket)
    await _feed(registry, cmd_id, {"type": "stream_chunk", "chunk": b"tok"})
    await consumer
    await stream.aclose()
    await _drain_pending_tasks()

    assert _delta(before, _cancellation_counts(), "aborted") == 1


@pytest.mark.asyncio
async def test_a_worker_that_cannot_cancel_is_counted_separately():
    """Distinguishes "nothing to abort" from "this node still leaks ghosts",
    which is what a rolling upgrade needs to be visible."""
    registry, websocket = _registry_with_session(actions=set())
    before = _cancellation_counts()

    stream = registry.send_stream_command(PROVIDER_ID, "infer_stream", {"lane_id": "lane-a"})
    consumer = asyncio.ensure_future(stream.__anext__())
    await asyncio.wait_for(websocket.stream_command_sent.wait(), timeout=1)
    cmd_id = _sent_stream_cmd_id(websocket)
    await _feed(registry, cmd_id, {"type": "stream_chunk", "chunk": b"tok"})
    await consumer
    await stream.aclose()
    await _drain_pending_tasks()

    after = _cancellation_counts()
    assert _delta(before, after, "unsupported") == 1
    assert _delta(before, after, "aborted") == 0


# ---------------------------------------------------------------------------
# An abandoned stream must not be recorded as a success
#
# The client closing the response raises GeneratorExit at the `yield`, so no
# exception reaches the handler and the request used to be logged as
# "success". It is not one: nobody read the answer and the generation was
# cancelled on the worker. It also means the disconnect count only ever saw
# the clients that left before the first token.
# ---------------------------------------------------------------------------


async def _run_streamer(monkeypatch, *, abandon_after: int | None, chunks: list[bytes] | None = None):
    from tests.unit.main.test_request_logging import _make_dummy_db, _make_pipeline

    import logos as main

    if chunks is None:
        chunks = [
            b'data: {"id":"c1","choices":[{"delta":{"content":"hel"}}]}\n\n',
            b'data: {"id":"c2","choices":[{"delta":{"content":"lo"}}]}\n\n',
            b"data: [DONE]\n\n",
        ]

    async def fake_send_stream_command(**kwargs):  # noqa: ARG001
        for chunk in chunks:
            yield chunk

    monkeypatch.setattr(main, "DBManager", _make_dummy_db())
    monkeypatch.setattr(
        main,
        "_context_resolver",
        SimpleNamespace(prepare_headers_and_payload=lambda context, payload: ({}, payload)),
        raising=False,
    )
    monkeypatch.setattr(
        main,
        "_logosnode_registry",
        SimpleNamespace(send_stream_command=fake_send_stream_command),
        raising=False,
    )
    completion_calls: list[dict] = []
    pipeline, _c, _r = _make_pipeline(completion_calls=completion_calls)
    monkeypatch.setattr(main, "_pipeline", pipeline, raising=False)

    response = await main._streaming_response(
        SimpleNamespace(provider_id=12, provider_type="logosnode", lane_id="lane-1", anthropic_dialect=None),
        {"messages": [{"role": "user", "content": "hi"}]},
        42,
        12,
        27,
        -1,
        {"policy": "ok"},
        {
            "request_id": "req-stream",
            "provider_type": "logosnode",
            "queue_depth_at_arrival": 0,
            "utilization_at_arrival": 1,
            "is_cold_start": False,
        },
    )

    body = response.body_iterator
    if abandon_after is None:
        async for _chunk in body:
            pass
    else:
        for _ in range(abandon_after):
            await body.__anext__()
        await body.aclose()
    return completion_calls


@pytest.mark.asyncio
async def test_a_stream_read_to_the_end_is_a_success(monkeypatch):
    calls = await _run_streamer(monkeypatch, abandon_after=None)
    assert calls[-1]["result_status"] == "success"
    assert calls[-1]["error_message"] is None


@pytest.mark.asyncio
async def test_a_stream_the_client_walked_away_from_is_not(monkeypatch):
    calls = await _run_streamer(monkeypatch, abandon_after=1)
    assert calls[-1]["result_status"] == "error"
    assert "disconnected mid-stream" in calls[-1]["error_message"]


@pytest.mark.asyncio
async def test_closing_after_done_is_a_success(monkeypatch):
    """GuideLLM closes after [DONE]; that is completion, not a disconnect."""
    calls = await _run_streamer(monkeypatch, abandon_after=3)
    assert calls[-1]["result_status"] == "success"
    assert calls[-1]["error_message"] is None


@pytest.mark.asyncio
async def test_the_recorded_reason_says_how_far_it_got(monkeypatch):
    """Distinguishes "left immediately" from "read most of it", which is what
    makes the number actionable."""
    calls = await _run_streamer(monkeypatch, abandon_after=1)
    assert "token(s)" in calls[-1]["error_message"]


@pytest.mark.asyncio
async def test_a_responses_api_failed_event_is_not_billed_or_recorded_as_success(monkeypatch):
    """A terminal ``response.failed`` frame closes the stream cleanly, so
    ``stream_completed`` is True; the request still failed and must be neither
    billed nor logged as a success."""
    calls = await _run_streamer(
        monkeypatch,
        abandon_after=None,
        chunks=[
            b'data: {"type":"response.output_text.delta","delta":"partial"}\n\n',
            b'data: {"type":"response.failed","response":{"id":"resp_1","status":"failed",'
            b'"error":{"code":"server_error","message":"the model is overloaded"}}}\n\n',
        ],
    )
    assert calls[-1]["result_status"] == "error"
    assert "overloaded" in calls[-1]["error_message"]
    assert "billed_requests" not in calls[-1]["usage_tokens"]


@pytest.mark.asyncio
async def test_an_in_band_error_frame_is_not_billed_or_recorded_as_success(monkeypatch):
    """A worker that passes an upstream ``data: {"error": ...}`` frame through
    and then closes the stream normally still produced a failed request."""
    calls = await _run_streamer(
        monkeypatch,
        abandon_after=None,
        chunks=[
            b'data: {"id":"c1","choices":[{"delta":{"content":"partial"}}]}\n\n',
            b'data: {"error":{"message":"content flagged mid-stream","type":"invalid_request_error"}}\n\n',
            b"data: [DONE]\n\n",
        ],
    )
    assert calls[-1]["result_status"] == "error"
    assert "content flagged mid-stream" in calls[-1]["error_message"]
    assert "billed_requests" not in calls[-1]["usage_tokens"]


@pytest.mark.asyncio
async def test_a_responses_api_incomplete_event_is_still_a_billed_success(monkeypatch):
    """``response.incomplete`` (max_output_tokens / content filter) returns real
    output the provider charges for, so it stays a billable success."""
    calls = await _run_streamer(
        monkeypatch,
        abandon_after=None,
        chunks=[
            b'data: {"type":"response.output_text.delta","delta":"partial"}\n\n',
            b'data: {"type":"response.incomplete","response":{"id":"resp_1","status":"incomplete",'
            b'"incomplete_details":{"reason":"max_output_tokens"},'
            b'"usage":{"input_tokens":5,"output_tokens":10,"total_tokens":15}}}\n\n',
        ],
    )
    assert calls[-1]["result_status"] == "success"
    assert calls[-1]["error_message"] is None
    assert calls[-1]["usage_tokens"]["billed_requests"] == 1
