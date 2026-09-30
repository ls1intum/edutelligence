"""The executor captures the dispatch and response instants around the HTTP
send so the statistics split excludes logos' request preparation and response
parsing from the provider's window."""

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
    def __init__(self, times):
        self._times = times

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
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
    """dispatch_at is captured after request preparation (before the send)
    and response_at after the response arrived (before body parsing), so both
    logos work items stay out of the provider's window."""
    times = {}
    monkeypatch.setattr(executor_module.httpx, "AsyncClient", lambda **_kwargs: _FakeAsyncClient(times))

    result = await Executor().execute_sync(URL, {}, {"model": "m", "messages": []})

    assert result.success
    assert result.dispatch_at is not None
    assert result.dispatch_at <= times["send_start"], "the dispatch instant must precede the HTTP send"
    assert times["send_end"] <= result.response_at, "the response instant must follow the HTTP response"
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
    def __init__(self, times):
        self._times = times

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    def stream(self, method, url, *, headers, **_kwargs):  # noqa: ARG002
        self._times["send_start"] = datetime.datetime.now(datetime.timezone.utc)
        return _FakeStreamResponse()


@pytest.mark.asyncio
async def test_execute_streaming_captures_the_dispatch_instant_before_the_send(monkeypatch):
    """The streaming dispatch instant is captured on the status object once
    the generator body starts — after preparation, before the send."""
    times = {}
    monkeypatch.setattr(executor_module.httpx, "AsyncClient", lambda **_kwargs: _FakeStreamingClient(times))
    status = StreamingExecutionStatus()

    async def _drain():
        async for _chunk in Executor().execute_streaming(URL, {}, {"model": "m", "messages": []}, status=status):
            pass

    await _drain()

    assert status.dispatch_at is not None
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
