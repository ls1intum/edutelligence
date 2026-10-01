"""The executor captures the dispatch and response instants around the HTTP
send so the statistics split excludes logos' request preparation, HTTP client
lifecycle, and response parsing from the provider's window."""

import asyncio
import datetime

import pytest

from logos.pipeline import executor as executor_module
from logos.pipeline.executor import Executor, StreamingExecutionStatus

URL = "https://provider.test/v1/chat/completions"


class _FakeSyncResponse:
    status_code = 200

    def __init__(self):
        self.headers = {"content-type": "application/json"}
        self.text = ""
        self.content = b""

    def json(self):
        return {"choices": [], "usage": {}}


class _FakeAsyncClient:
    def __init__(self, times, *, setup_delay=0.0, teardown_delay=0.0):
        self._times = times
        self._setup_delay = setup_delay
        self._teardown_delay = teardown_delay

    async def __aenter__(self):
        if self._setup_delay:
            await asyncio.sleep(self._setup_delay)
        self._times["enter_end"] = datetime.datetime.now(datetime.timezone.utc)
        return self

    async def __aexit__(self, *_args):
        self._times["exit_start"] = datetime.datetime.now(datetime.timezone.utc)
        if self._teardown_delay:
            await asyncio.sleep(self._teardown_delay)
        return None

    async def post(self, url, *, headers, timeout, json):  # noqa: ARG002
        self._times["send_start"] = datetime.datetime.now(datetime.timezone.utc)
        await asyncio.sleep(0.02)  # the provider's own time
        self._times["send_end"] = datetime.datetime.now(datetime.timezone.utc)
        return _FakeSyncResponse()


def _fail_preparation(payload):  # noqa: ARG001
    raise ValueError("multipart decode failed")


@pytest.mark.asyncio
async def test_execute_sync_captures_the_instants_around_the_http_send(monkeypatch):
    """dispatch_at is captured after request preparation and client setup
    (immediately before the send) and response_at after the response arrived
    (before client teardown and body parsing), so logos work stays out of the
    provider's window."""
    times = {}
    monkeypatch.setattr(
        executor_module.httpx,
        "AsyncClient",
        lambda **_kwargs: _FakeAsyncClient(times, setup_delay=0.02, teardown_delay=0.02),
    )

    result = await Executor().execute_sync(URL, {}, {"model": "m", "messages": []})

    assert result.success
    assert result.dispatch_at is not None
    assert result.response_at is not None
    # Client setup finished before the dispatch stamp…
    assert times["enter_end"] <= result.dispatch_at
    # …dispatch precedes the HTTP send…
    assert result.dispatch_at <= times["send_start"], "the dispatch instant must precede the HTTP send"
    # …response follows the HTTP response…
    assert times["send_end"] <= result.response_at, "the response instant must follow the HTTP response"
    # …and precedes client teardown.
    assert result.response_at <= times["exit_start"], "the response instant must precede client teardown"
    assert result.dispatch_at < result.response_at


@pytest.mark.asyncio
async def test_execute_sync_preparation_failure_captures_no_instants(monkeypatch):
    """A request that fails during preparation never reaches the provider:
    both captured instants stay None, so the caller stamps no provider call."""
    monkeypatch.setattr(Executor, "_request_kwargs", staticmethod(_fail_preparation))

    result = await Executor().execute_sync(URL, {}, {"model": "m", "messages": []})

    assert not result.success
    assert "multipart decode failed" in result.error
    assert result.dispatch_at is None
    assert result.response_at is None


@pytest.mark.asyncio
async def test_execute_sync_client_init_failure_captures_no_dispatch(monkeypatch):
    """A client that fails to open never sent anything: dispatch_at stays None
    even though preparation succeeded."""

    class _FailingClient:
        def __init__(self, **_kwargs):
            raise OSError("client init failed")

    monkeypatch.setattr(executor_module.httpx, "AsyncClient", _FailingClient)

    result = await Executor().execute_sync(URL, {}, {"model": "m", "messages": []})

    assert not result.success
    assert "client init failed" in result.error
    assert result.dispatch_at is None
    assert result.response_at is None


class _FakeStreamResponse:
    status_code = 200

    def __init__(self):
        self.headers = {"content-type": "text/event-stream"}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def aiter_bytes(self):
        yield b"data: [DONE]\n\n"


class _FakeStreamingClient:
    def __init__(self, times, *, setup_delay=0.0):
        self._times = times
        self._setup_delay = setup_delay

    async def __aenter__(self):
        if self._setup_delay:
            await asyncio.sleep(self._setup_delay)
        self._times["enter_end"] = datetime.datetime.now(datetime.timezone.utc)
        return self

    async def __aexit__(self, *_args):
        return None

    def stream(self, method, url, *, headers, **_kwargs):  # noqa: ARG002
        self._times["send_start"] = datetime.datetime.now(datetime.timezone.utc)
        return _FakeStreamResponse()


@pytest.mark.asyncio
async def test_execute_streaming_captures_the_dispatch_instant_before_the_send(monkeypatch):
    """The streaming dispatch instant is captured inside the entered client
    context immediately before the send — after preparation and client setup."""
    times = {}
    monkeypatch.setattr(
        executor_module.httpx,
        "AsyncClient",
        lambda **_kwargs: _FakeStreamingClient(times, setup_delay=0.02),
    )
    status = StreamingExecutionStatus()

    async def _drain():
        async for _chunk in Executor().execute_streaming(URL, {}, {"model": "m", "messages": []}, status=status):
            pass

    await _drain()

    assert status.dispatch_at is not None
    assert times["enter_end"] <= status.dispatch_at, "client setup must finish before the dispatch stamp"
    assert status.dispatch_at <= times["send_start"], "the dispatch instant must precede the HTTP send"


@pytest.mark.asyncio
async def test_execute_streaming_preparation_failure_captures_no_dispatch(monkeypatch):
    """When preparation fails inside the generator, dispatch_at stays unset:
    the request never reached the provider."""
    monkeypatch.setattr(Executor, "_request_kwargs", staticmethod(_fail_preparation))
    status = StreamingExecutionStatus()

    async def _drain():
        with pytest.raises(ValueError, match="multipart decode failed"):
            async for _chunk in Executor().execute_streaming(URL, {}, {"model": "m", "messages": []}, status=status):
                pass

    await _drain()

    assert status.dispatch_at is None


@pytest.mark.asyncio
async def test_execute_streaming_client_init_failure_captures_no_dispatch(monkeypatch):
    """A streaming client that fails to open never sent anything: dispatch_at
    stays unset."""

    class _FailingClient:
        def __init__(self, **_kwargs):
            raise OSError("client init failed")

    monkeypatch.setattr(executor_module.httpx, "AsyncClient", _FailingClient)
    status = StreamingExecutionStatus()

    async def _drain():
        with pytest.raises(OSError, match="client init failed"):
            async for _chunk in Executor().execute_streaming(URL, {}, {"model": "m", "messages": []}, status=status):
                pass

    await _drain()

    assert status.dispatch_at is None
