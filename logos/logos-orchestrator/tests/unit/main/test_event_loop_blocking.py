"""Regression guard: slow synchronous DB work must not block the event loop.

Before the with_db offload, a slow stats query (or a streaming finalization
write) executed directly on the event loop, pausing every in-flight streaming
response. These tests run a heartbeat watchdog while exercising those paths
against a deliberately slow DB stub and assert the loop keeps scheduling on
time.
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

import logos as main
from logos.dbutils import dbmanager as dbmanager_module

SLOW_QUERY_SECONDS = 1.0
# Generous bound for CI jitter; a blocking query stalls the loop for the
# full SLOW_QUERY_SECONDS, so the two regimes are far apart.
MAX_ALLOWED_DRIFT_SECONDS = 0.5
HEARTBEAT_INTERVAL = 0.05


class _LoopWatchdog:
    """Measures how late the event loop schedules a periodic heartbeat."""

    def __init__(self):
        self.max_drift = 0.0
        self._stop = asyncio.Event()
        self._task = None

    async def _run(self):
        loop = asyncio.get_running_loop()
        prev = loop.time()
        while not self._stop.is_set():
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            now = loop.time()
            self.max_drift = max(self.max_drift, now - prev - HEARTBEAT_INTERVAL)
            prev = now

    async def __aenter__(self):
        self._task = asyncio.create_task(self._run())
        # Yield once so the watchdog is ticking before the guarded work runs —
        # a loop-blocking path would otherwise finish before its first beat.
        await asyncio.sleep(0)
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self._stop.set()
        await self._task


def _patch_db(monkeypatch, db_factory):
    monkeypatch.setattr(main, "DBManager", db_factory)
    monkeypatch.setattr(dbmanager_module, "DBManager", db_factory)


def _make_request(body=None, headers=None):
    request = MagicMock()
    request.headers = headers or {"authorization": "Bearer test-key"}
    request.json = AsyncMock(return_value=body or {})
    return request


@pytest.fixture(autouse=True)
def mock_auth(monkeypatch):
    auth_ctx = MagicMock()
    auth_ctx.key_value = "test-key"
    monkeypatch.setattr(main, "authenticate_api_key", lambda headers: auth_ctx)


@pytest.mark.asyncio
async def test_vram_stats_does_not_block_event_loop(monkeypatch):
    class SlowStatsDB:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get_ollama_vram_stats(self, logos_key, day, bucket_seconds=5):
            time.sleep(SLOW_QUERY_SECONDS)
            return {"providers": [], "last_snapshot_id": 0}, 200

        def get_local_provider_inventory(self, logos_key):
            return [], 200

    _patch_db(monkeypatch, SlowStatsDB)

    async with _LoopWatchdog() as watchdog:
        response = await main.get_ollama_vram_stats(_make_request(body={"day": "2026-01-01"}))

    assert response.status_code == 200
    assert watchdog.max_drift < MAX_ALLOWED_DRIFT_SECONDS, (
        f"Event loop stalled {watchdog.max_drift:.3f}s during a "
        f"{SLOW_QUERY_SECONDS}s stats query — sync DB work is back on the loop"
    )


@pytest.mark.asyncio
async def test_streaming_finalization_does_not_block_event_loop(monkeypatch):
    class SlowWriteDB:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def set_time_at_first_token(self, log_id, timestamp=None):
            time.sleep(SLOW_QUERY_SECONDS / 2)

        def set_response_payload(self, *args, **kwargs):
            time.sleep(SLOW_QUERY_SECONDS)

        def update_log_entry_metrics(self, **kwargs):
            pass

    _patch_db(monkeypatch, SlowWriteDB)

    class DummyExecutor:
        async def execute_streaming(self, url, headers, payload, on_headers=None):  # noqa: ARG002
            if on_headers:
                on_headers({})
            yield b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n'
            yield b"data: [DONE]\n\n"

    class DummyPipeline:
        executor = DummyExecutor()

        @staticmethod
        def update_provider_stats(model_id, provider_id, headers):  # noqa: ARG002
            return None

    monkeypatch.setattr(main, "_pipeline", DummyPipeline(), raising=False)

    async with _LoopWatchdog() as watchdog:
        response = main._proxy_streaming_response(
            "http://proxy",
            {"Authorization": "Bearer x"},
            {"stream": True},
            7,
            1,
            2,
            -1,
            {},
            request_id="req-loop-guard",
        )
        async for _ in response.body_iterator:
            pass
        # TTFT is written fire-and-forget; include it in the guarded window.
        while main._background_tasks:
            await asyncio.gather(*list(main._background_tasks))

    assert watchdog.max_drift < MAX_ALLOWED_DRIFT_SECONDS, (
        f"Event loop stalled {watchdog.max_drift:.3f}s during streaming "
        f"DB writes — sync DB work is back on the loop"
    )
