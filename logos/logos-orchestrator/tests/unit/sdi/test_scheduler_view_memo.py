"""Per-revision memoisation of the scheduler views (#980 O15).

``get_model_scheduler_view`` / ``get_all_lane_signals`` are pure functions of
the latest runtime snapshot, and ``update_runtime`` replaces that snapshot and
bumps ``runtime_revision`` in one step — so within one revision they must
return the cached object, and rebuild the moment the revision moves.
"""

from __future__ import annotations

import pytest

from logos.logosnode_registry import LogosNodeRuntimeRegistry, ProviderSession
from logos.queue import PriorityQueueManager
from logos.sdi.logosnode_facade import LogosNodeSchedulingDataFacade


def _lane(lane_id="lane-1", model="m1", active_requests=0):
    return {
        "lane_id": lane_id,
        "model": model,
        "runtime_state": "loaded",
        "sleep_state": "unsupported",
        "active_requests": active_requests,
        "num_parallel": 1,
        "effective_vram_mb": 8192.0,
        "backend_metrics": {},
        "lane_config": {"vllm_config": {"gpu_memory_utilization": 0.7, "tensor_parallel_size": 1}},
        "loaded_models": [{"name": model}],
    }


@pytest.fixture
def facade(monkeypatch):
    registry = LogosNodeRuntimeRegistry()
    registry._sessions[7] = ProviderSession(  # noqa: SLF001
        provider_id=7,
        worker_id="worker-a",
        websocket=object(),
    )
    monkeypatch.setattr(
        "logos.sdi.providers.logosnode_provider.LogosNodeDataProvider._load_provider_config",
        lambda self: {},
    )
    monkeypatch.setattr(
        "logos.sdi.providers.logosnode_provider.LogosNodeDataProvider._fetch_ps_data",
        lambda self: {"models": []},
    )
    f = LogosNodeSchedulingDataFacade(PriorityQueueManager(), runtime_registry=registry)
    f.register_model(101, "logosnode", "http://fake", "m1", 65536, provider_id=7)
    return f, registry


@pytest.mark.asyncio
async def test_view_is_memoised_within_one_revision(facade):
    f, registry = facade
    await registry.update_runtime(7, {"lanes": [_lane()]})

    first = f.get_model_scheduler_view(101, provider_id=7)
    second = f.get_model_scheduler_view(101, provider_id=7)

    assert first is not None
    assert second is first  # same revision → cached object, no rebuild
    signals_a = f.get_all_provider_lane_signals(7)
    signals_b = f.get_all_provider_lane_signals(7)
    assert signals_a
    assert signals_a is signals_b


@pytest.mark.asyncio
async def test_view_rebuilds_when_the_revision_moves(facade):
    f, registry = facade
    await registry.update_runtime(7, {"lanes": [_lane(active_requests=1)]})
    first = f.get_model_scheduler_view(101, provider_id=7)

    # A new status push replaces the snapshot and bumps the revision: the
    # rebuilt view must see the fresh lane counts.
    await registry.update_runtime(7, {"lanes": [_lane(active_requests=5)]})
    second = f.get_model_scheduler_view(101, provider_id=7)

    assert second is not first
    assert first.aggregate_active_requests == 1
    assert second.aggregate_active_requests == 5


@pytest.mark.asyncio
async def test_lane_signals_rebuild_with_the_revision(facade):
    f, registry = facade
    await registry.update_runtime(7, {"lanes": [_lane(active_requests=1)]})
    first = f.get_all_provider_lane_signals(7)

    await registry.update_runtime(7, {"lanes": [_lane(active_requests=5)]})
    second = f.get_all_provider_lane_signals(7)

    assert second is not first
    assert first[0].active_requests == 1
    assert second[0].active_requests == 5
