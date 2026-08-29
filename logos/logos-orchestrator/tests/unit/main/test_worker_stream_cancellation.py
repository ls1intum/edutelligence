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

from logos.logosnode_registry import CANCEL_COMMAND_ACTION, LogosNodeRuntimeRegistry, ProviderSession

PROVIDER_ID = 7


class _FakeWebSocket:
    """Records outbound frames and lets a test answer command RPCs."""

    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.auto_ack = True
        self._registry: LogosNodeRuntimeRegistry | None = None

    def bind(self, registry: LogosNodeRuntimeRegistry) -> None:
        self._registry = registry

    async def send_json(self, message: dict) -> None:
        self.sent.append(message)
        if self.auto_ack and self._registry is not None and message.get("action") == CANCEL_COMMAND_ACTION:
            # Answer the cancel RPC the way a worker would, so the
            # fire-and-forget task completes instead of timing out.
            await self._registry.on_command_result(
                PROVIDER_ID,
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
    await asyncio.sleep(0)
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
    await asyncio.sleep(0)
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
    await asyncio.sleep(0)
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
    await asyncio.sleep(0)
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
    await asyncio.sleep(0)
    cmd_id = _sent_stream_cmd_id(websocket)
    await _feed(registry, cmd_id, {"type": "stream_chunk", "chunk": b"tok"})
    await consumer

    await stream.aclose()
    await _drain_pending_tasks()
    assert cmd_id not in registry._sessions[PROVIDER_ID].pending_streams


# ---------------------------------------------------------------------------
# Non-streaming path — same exposure, same fix
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_abandoned_sync_infer_is_cancelled_on_the_worker():
    registry, websocket = _registry_with_session()

    call = asyncio.ensure_future(registry.send_command(PROVIDER_ID, "infer", {"lane_id": "lane-a"}))
    await asyncio.sleep(0)
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
        SimpleNamespace(provider_id=12, provider_type="logosnode", lane_id="lane-1"),
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
            SimpleNamespace(provider_id=PROVIDER_ID, provider_type="logosnode", lane_id="lane-1"),
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
    await asyncio.sleep(0)
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
    await asyncio.sleep(0)
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
    await asyncio.sleep(0)
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


async def _run_streamer(monkeypatch, *, abandon_after: int | None):
    from tests.unit.main.test_request_logging import _make_dummy_db, _make_pipeline

    import logos as main

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
        SimpleNamespace(provider_id=12, provider_type="logosnode", lane_id="lane-1"),
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
async def test_the_recorded_reason_says_how_far_it_got(monkeypatch):
    """Distinguishes "left immediately" from "read most of it", which is what
    makes the number actionable."""
    calls = await _run_streamer(monkeypatch, abandon_after=1)
    assert "token(s)" in calls[-1]["error_message"]
