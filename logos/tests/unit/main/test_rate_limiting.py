from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

import logos.main as main
from logos.auth import AuthContext
from logos.rate_limiter import InMemoryRateLimiter, RateLimitConfig, set_rate_limiter


def _auth(api_key_id: int = 1, cloud_rl=None, local_rl=None) -> AuthContext:
    return AuthContext(
        key_value="lg-test",
        api_key_id=api_key_id,
        api_key_name="Test",
        key_type="developer",
        team_id=None,
        user_id=None,
        environment=None,
        log_level="BILLING",
        settings={},
        cloud_rl=cloud_rl,
        local_rl=local_rl,
    )


def _pipeline_result(provider_type: str, model_id: int = 27, provider_id: int = 12):
    result = MagicMock()
    result.success = True
    result.model_id = model_id
    result.provider_id = provider_id
    result.execution_context = MagicMock()
    result.classification_stats = {}
    result.scheduling_stats = {
        "request_id": "req-1",
        "provider_type": provider_type,
        "model_id": model_id,
        "provider_id": provider_id,
        "queue_depth": 0,
        "queue_depth_at_arrival": 0,
        "utilization_at_arrival": 0.0,
        "is_cold_start": False,
    }
    result.error = None
    return result


class _TrackingRateLimiter(InMemoryRateLimiter):

    def __init__(self):
        super().__init__()
        self.checked_keys: list[str] = []

    def check_and_record(self, key: str, config: RateLimitConfig):
        self.checked_keys.append(key)
        return super().check_and_record(key, config)


def _fake_scheduler():
    sched = MagicMock()
    sched.release = MagicMock()
    return sched


def _patch_pipeline(monkeypatch, provider_type: str, scheduler=None):
    result = _pipeline_result(provider_type)
    sched = scheduler or _fake_scheduler()

    pipeline = MagicMock()
    pipeline.process = AsyncMock(return_value=result)
    pipeline.scheduler = sched

    monkeypatch.setattr(main, "_pipeline", pipeline, raising=False)
    monkeypatch.setattr(main, "_extract_policy", lambda *a, **kw: None)
    monkeypatch.setattr(main, "_sync_response", AsyncMock(return_value={"ok": True}))
    monkeypatch.setattr(main, "_record_log_failure", lambda *a, **kw: None)

    return pipeline, result, sched


@pytest.mark.asyncio
async def test_cloud_request_uses_cloud_rl_key(monkeypatch):
    limiter = _TrackingRateLimiter()
    set_rate_limiter(limiter)

    _patch_pipeline(monkeypatch, provider_type="cloud")

    await main._execute_resource_mode(
        deployments=[{"model_id": 27, "provider_id": 12, "type": "cloud"}],
        body={},
        headers={},
        auth=_auth(api_key_id=5, cloud_rl={"rpm": 10, "tpm": None}),
        log_id=None,
        is_async_job=False,
    )

    assert "api_key:5:cloud" in limiter.checked_keys
    assert "api_key:5:local" not in limiter.checked_keys


@pytest.mark.asyncio
async def test_local_request_uses_local_rl_key(monkeypatch):
    limiter = _TrackingRateLimiter()
    set_rate_limiter(limiter)

    _patch_pipeline(monkeypatch, provider_type="logosnode")

    await main._execute_resource_mode(
        deployments=[{"model_id": 27, "provider_id": 12, "type": "logosnode"}],
        body={},
        headers={},
        auth=_auth(api_key_id=7, local_rl={"rpm": 10, "tpm": None}),
        log_id=None,
        is_async_job=False,
    )

    assert "api_key:7:local" in limiter.checked_keys
    assert "api_key:7:cloud" not in limiter.checked_keys


@pytest.mark.asyncio
async def test_cloud_rate_limit_exceeded_raises_429(monkeypatch):
    limiter = InMemoryRateLimiter()
    set_rate_limiter(limiter)
    limiter.check_and_record("api_key:1:cloud", RateLimitConfig(rpm=1))

    _patch_pipeline(monkeypatch, provider_type="cloud")

    with pytest.raises(main.HTTPException) as exc:
        await main._execute_resource_mode(
            deployments=[{"model_id": 27, "provider_id": 12, "type": "cloud"}],
            body={},
            headers={},
            auth=_auth(api_key_id=1, cloud_rl={"rpm": 1, "tpm": None}),
            log_id=None,
            is_async_job=False,
        )

    assert exc.value.status_code == 429
    assert "rate limit" in exc.value.detail.lower()


@pytest.mark.asyncio
async def test_local_rate_limit_exceeded_raises_429(monkeypatch):
    limiter = InMemoryRateLimiter()
    set_rate_limiter(limiter)
    limiter.check_and_record("api_key:2:local", RateLimitConfig(rpm=1))

    _patch_pipeline(monkeypatch, provider_type="logosnode")

    with pytest.raises(main.HTTPException) as exc:
        await main._execute_resource_mode(
            deployments=[{"model_id": 27, "provider_id": 12, "type": "logosnode"}],
            body={},
            headers={},
            auth=_auth(api_key_id=2, local_rl={"rpm": 1, "tpm": None}),
            log_id=None,
            is_async_job=False,
        )

    assert exc.value.status_code == 429


@pytest.mark.asyncio
async def test_rate_limit_exceeded_async_returns_dict(monkeypatch):
    limiter = InMemoryRateLimiter()
    set_rate_limiter(limiter)
    limiter.check_and_record("api_key:3:cloud", RateLimitConfig(rpm=1))

    _patch_pipeline(monkeypatch, provider_type="cloud")

    result = await main._execute_resource_mode(
        deployments=[{"model_id": 27, "provider_id": 12, "type": "cloud"}],
        body={},
        headers={},
        auth=_auth(api_key_id=3, cloud_rl={"rpm": 1, "tpm": None}),
        log_id=None,
        is_async_job=True,
    )

    assert result["status_code"] == 429
    assert "error" in result["data"]


@pytest.mark.asyncio
async def test_scheduler_slot_released_on_cloud_rate_limit(monkeypatch):
    limiter = InMemoryRateLimiter()
    set_rate_limiter(limiter)
    limiter.check_and_record("api_key:4:cloud", RateLimitConfig(rpm=1))

    sched = _fake_scheduler()
    _patch_pipeline(monkeypatch, provider_type="cloud", scheduler=sched)

    with pytest.raises(main.HTTPException):
        await main._execute_resource_mode(
            deployments=[{"model_id": 27, "provider_id": 12, "type": "cloud"}],
            body={},
            headers={},
            auth=_auth(api_key_id=4, cloud_rl={"rpm": 1, "tpm": None}),
            log_id=None,
            is_async_job=False,
        )

    sched.release.assert_called_once_with(27, 12, "cloud", "req-1")


@pytest.mark.asyncio
async def test_scheduler_slot_released_on_local_rate_limit(monkeypatch):
    limiter = InMemoryRateLimiter()
    set_rate_limiter(limiter)
    limiter.check_and_record("api_key:5:local", RateLimitConfig(rpm=1))

    sched = _fake_scheduler()
    _patch_pipeline(monkeypatch, provider_type="logosnode", scheduler=sched)

    with pytest.raises(main.HTTPException):
        await main._execute_resource_mode(
            deployments=[{"model_id": 27, "provider_id": 12, "type": "logosnode"}],
            body={},
            headers={},
            auth=_auth(api_key_id=5, local_rl={"rpm": 1, "tpm": None}),
            log_id=None,
            is_async_job=False,
        )

    sched.release.assert_called_once_with(27, 12, "logosnode", "req-1")


@pytest.mark.asyncio
async def test_exhausted_cloud_limit_does_not_block_local(monkeypatch):
    limiter = InMemoryRateLimiter()
    set_rate_limiter(limiter)
    limiter.check_and_record("api_key:6:cloud", RateLimitConfig(rpm=1))

    _patch_pipeline(monkeypatch, provider_type="logosnode")

    await main._execute_resource_mode(
        deployments=[{"model_id": 27, "provider_id": 12, "type": "logosnode"}],
        body={},
        headers={},
        auth=_auth(api_key_id=6, cloud_rl={"rpm": 1}, local_rl={"rpm": 5}),
        log_id=None,
        is_async_job=False,
    )


@pytest.mark.asyncio
async def test_exhausted_local_limit_does_not_block_cloud(monkeypatch):
    limiter = InMemoryRateLimiter()
    set_rate_limiter(limiter)
    limiter.check_and_record("api_key:7:local", RateLimitConfig(rpm=1))

    _patch_pipeline(monkeypatch, provider_type="azure")

    await main._execute_resource_mode(
        deployments=[{"model_id": 27, "provider_id": 12, "type": "azure"}],
        body={},
        headers={},
        auth=_auth(api_key_id=7, cloud_rl={"rpm": 5}, local_rl={"rpm": 1}),
        log_id=None,
        is_async_job=False,
    )


@pytest.mark.asyncio
async def test_no_rl_config_skips_rate_limit_check(monkeypatch):
    limiter = _TrackingRateLimiter()
    set_rate_limiter(limiter)

    _patch_pipeline(monkeypatch, provider_type="cloud")

    await main._execute_resource_mode(
        deployments=[{"model_id": 27, "provider_id": 12, "type": "cloud"}],
        body={},
        headers={},
        auth=_auth(api_key_id=99, cloud_rl=None, local_rl=None),
        log_id=None,
        is_async_job=False,
    )

    assert limiter.checked_keys == []
