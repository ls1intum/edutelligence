"""Tests for the temp-provider health monitor."""

import asyncio
import time

import httpx
import pytest

from logos.temp_providers.discovery import DiscoveredModel
from logos.temp_providers.health_monitor import HealthMonitor, _check_provider_health
from logos.temp_providers.registry import TempProviderRegistry


@pytest.fixture(autouse=True)
def _reset_registry():
    TempProviderRegistry.reset_singleton()
    yield
    TempProviderRegistry.reset_singleton()


# ------------------------------------------------------------------
# _check_provider_health
# ------------------------------------------------------------------


class _OkClient:
    async def __aenter__(self):
        return self
    async def __aexit__(self, *a):
        pass
    async def get(self, url, **kw):
        class R:
            status_code = 200
        return R()


class _FailClient:
    async def __aenter__(self):
        return self
    async def __aexit__(self, *a):
        pass
    async def get(self, *a, **kw):
        raise httpx.ConnectError("refused")


@pytest.mark.asyncio
async def test_check_health_reachable(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _OkClient())
    assert await _check_provider_health("http://localhost:1234") is True


@pytest.mark.asyncio
async def test_check_health_unreachable(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _FailClient())
    assert await _check_provider_health("http://localhost:1234") is False


# ------------------------------------------------------------------
# HealthMonitor.run_once
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_once_marks_unhealthy(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _FailClient())

    reg = TempProviderRegistry()
    prov = reg.register(url="http://x", name="x", owner_process_id=1, models=[])
    assert prov.is_healthy is True

    monitor = HealthMonitor(registry=reg)
    await monitor.run_once()

    assert reg.get(prov.id).is_healthy is False


@pytest.mark.asyncio
async def test_run_once_marks_healthy_again(monkeypatch):
    reg = TempProviderRegistry()
    prov = reg.register(url="http://x", name="x", owner_process_id=1, models=[])
    reg.mark_unhealthy(prov.id)

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _OkClient())

    monitor = HealthMonitor(registry=reg)
    await monitor.run_once()

    assert reg.get(prov.id).is_healthy is True


@pytest.mark.asyncio
async def test_run_once_auto_removes_stale(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _FailClient())

    reg = TempProviderRegistry()
    prov = reg.register(url="http://x", name="x", owner_process_id=1, models=[])
    reg.mark_unhealthy(prov.id)
    # Pretend it's been unhealthy for 10 minutes
    reg.get(prov.id).unhealthy_since = time.time() - 600

    monitor = HealthMonitor(auto_remove_after_s=300, registry=reg)
    await monitor.run_once()

    assert reg.get(prov.id) is None


# ------------------------------------------------------------------
# start / stop lifecycle
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_stop():
    reg = TempProviderRegistry()
    monitor = HealthMonitor(interval_s=0.05, registry=reg)
    monitor.start()
    assert monitor._task is not None
    await asyncio.sleep(0.15)  # let it tick a couple of times
    await monitor.stop()
    assert monitor._task is None


@pytest.mark.asyncio
async def test_stop_idempotent():
    reg = TempProviderRegistry()
    monitor = HealthMonitor(registry=reg)
    await monitor.stop()  # should not raise even when never started
    assert monitor._task is None
