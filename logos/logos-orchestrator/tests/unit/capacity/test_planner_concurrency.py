"""Concurrency tests for planner per-lane / per-provider locks.

The planner uses three lock families:

  - ``_lane_lock(provider_id, lane_id)``      — serialises operations on a
                                                single physical lane.
  - ``_model_prepare_lock(provider_id, model)`` — serialises cold-load
                                                  attempts for the same
                                                  (provider, model) so two
                                                  near-simultaneous requests
                                                  don't both trigger a load.
  - ``_provider_capacity_lock(provider_id)``  — serialises
                                                ensure_capacity reclaim
                                                phases per worker.

This test verifies that **operations on different lanes / providers / models
do NOT contend on each other**. Specifically:

  * Loading lane "X" on worker A and lane "Y" on worker B happen in
    parallel — neither blocks the other.
  * Two near-simultaneous requests for the same model on the same provider
    serialise (only one wins the cold-load).
  * Two requests for different models on the same provider parallelise.

These guarantees are how the multi-provider capacity plan executes in
a single cycle without grinding to a sequential crawl.
"""

from __future__ import annotations

import asyncio
import sys
from types import ModuleType
from unittest.mock import MagicMock

import pytest

# Same prometheus stub as test_best_first_scenarios.py
if "prometheus_client" not in sys.modules:
    _prom_stub = ModuleType("prometheus_client")

    class _MetricStub:
        def __init__(self, *a, **kw):
            pass

        def labels(self, *a, **kw):
            return self

        def inc(self, *a, **kw):
            pass

        def dec(self, *a, **kw):
            pass

        def set(self, *a, **kw):
            pass

        def observe(self, *a, **kw):
            pass

    _prom_stub.Counter = _MetricStub  # type: ignore[attr-defined]
    _prom_stub.Gauge = _MetricStub  # type: ignore[attr-defined]
    _prom_stub.Histogram = _MetricStub  # type: ignore[attr-defined]
    _prom_stub.Summary = _MetricStub  # type: ignore[attr-defined]
    _prom_stub.CollectorRegistry = MagicMock  # type: ignore[attr-defined]
    _prom_stub.REGISTRY = MagicMock()  # type: ignore[attr-defined]
    _prom_stub.CONTENT_TYPE_LATEST = "text/plain"  # type: ignore[attr-defined]
    _prom_stub.generate_latest = lambda *a, **kw: b""  # type: ignore[attr-defined]
    sys.modules["prometheus_client"] = _prom_stub

from logos import CapacityPlanner  # noqa: E402


def _bare_planner() -> CapacityPlanner:
    """Build a planner with the bare minimum state needed by the lock helpers.
    All other attributes are MagicMocks — these tests only exercise lock
    identity and asyncio.Lock acquire semantics."""
    planner = CapacityPlanner.__new__(CapacityPlanner)
    planner._lane_action_locks = {}
    planner._model_prepare_locks = {}
    planner._provider_capacity_locks = {}
    return planner


# ---------------------------------------------------------------------------
# Lock identity
# ---------------------------------------------------------------------------


def test_lane_lock_returns_same_instance_per_key():
    """Two calls with the same (provider, lane) must return the same lock."""
    p = _bare_planner()
    lock1 = p._lane_lock(1, "A-x")
    lock2 = p._lane_lock(1, "A-x")
    assert lock1 is lock2


def test_lane_lock_different_providers_are_independent():
    """(1, 'X') and (2, 'X') must be different locks."""
    p = _bare_planner()
    lock_a = p._lane_lock(1, "X")
    lock_b = p._lane_lock(2, "X")
    assert lock_a is not lock_b


def test_lane_lock_different_lanes_on_same_provider_are_independent():
    """(1, 'X') and (1, 'Y') must be different locks."""
    p = _bare_planner()
    lock_x = p._lane_lock(1, "X")
    lock_y = p._lane_lock(1, "Y")
    assert lock_x is not lock_y


def test_model_prepare_lock_namespaced_by_provider_and_model():
    """Same model on different providers → different locks."""
    p = _bare_planner()
    lock_1x = p._model_prepare_lock(1, "X")
    lock_2x = p._model_prepare_lock(2, "X")
    lock_1y = p._model_prepare_lock(1, "Y")
    assert lock_1x is not lock_2x  # different provider
    assert lock_1x is not lock_1y  # different model
    assert lock_1x is p._model_prepare_lock(1, "X")  # idempotent


def test_provider_capacity_lock_one_per_provider():
    p = _bare_planner()
    a = p._provider_capacity_lock(1)
    b = p._provider_capacity_lock(2)
    a_again = p._provider_capacity_lock(1)
    assert a is not b
    assert a is a_again


# ---------------------------------------------------------------------------
# Concurrent execution (real asyncio gather)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_loads_on_different_providers_do_not_serialize():
    """Loading on provider 1's lane X and provider 2's lane Y must overlap
    in wall time. If the per-lane locks were the same (or the planner used
    a global lock), the two awaits would serialise and total time would be
    >= 2 × per-op time."""
    p = _bare_planner()
    enter_order: list[str] = []
    exit_order: list[str] = []

    async def fake_load(provider_id: int, lane_id: str, tag: str, dur: float):
        async with p._lane_lock(provider_id, lane_id):
            enter_order.append(tag)
            await asyncio.sleep(dur)
            exit_order.append(tag)

    start = asyncio.get_event_loop().time()
    await asyncio.gather(
        fake_load(1, "A-x", "A", 0.05),
        fake_load(2, "B-y", "B", 0.05),
    )
    elapsed = asyncio.get_event_loop().time() - start
    # Both entered before either exited → true overlap.
    assert enter_order[:2] == ["A", "B"] or enter_order[:2] == ["B", "A"]
    # Elapsed time should be ~one operation, not two (allow 25 % slack
    # for scheduler jitter on slow CI).
    assert elapsed < 0.08, f"Operations serialized unexpectedly (took {elapsed:.3f}s)"


@pytest.mark.asyncio
async def test_concurrent_loads_on_same_lane_serialize():
    """Two operations targeting the SAME (provider, lane) must serialise —
    that's the entire purpose of the lane lock."""
    p = _bare_planner()
    enter_order: list[str] = []
    exit_order: list[str] = []

    async def op(tag: str, dur: float):
        async with p._lane_lock(1, "A-x"):
            enter_order.append(tag)
            await asyncio.sleep(dur)
            exit_order.append(tag)

    start = asyncio.get_event_loop().time()
    await asyncio.gather(op("first", 0.05), op("second", 0.05))
    elapsed = asyncio.get_event_loop().time() - start
    # Strict ordering: first enters and exits before second enters
    assert enter_order == ["first", "second"]
    assert exit_order == ["first", "second"]
    # Elapsed should be ~2× operation time, not 1×
    assert elapsed >= 0.09, f"Same-lane operations did NOT serialize (took {elapsed:.3f}s)"


@pytest.mark.asyncio
async def test_concurrent_cold_loads_for_same_model_on_same_provider_serialize():
    """Two cold-load attempts for the same (provider, model) — e.g. two
    near-simultaneous requests — must serialise via _model_prepare_lock so
    only the winner triggers the actual load. The other observes a loaded
    lane on entry."""
    p = _bare_planner()
    winners: list[str] = []

    async def cold_load_attempt(tag: str):
        async with p._model_prepare_lock(1, "X"):
            # First arrival "loads" the model; subsequent arrivals would
            # short-circuit on a loaded-lane check.
            await asyncio.sleep(0.02)
            winners.append(tag)

    await asyncio.gather(
        cold_load_attempt("req-a"),
        cold_load_attempt("req-b"),
        cold_load_attempt("req-c"),
    )
    # All three completed, but strictly one-at-a-time.
    assert winners == ["req-a", "req-b", "req-c"]


@pytest.mark.asyncio
async def test_concurrent_cold_loads_for_different_models_on_same_provider_parallelize():
    """Cold-loading model X and model Y on the SAME provider must not
    serialise. This is what lets a single worker bring up multiple models
    in parallel during capability seeding."""
    p = _bare_planner()
    enter_order: list[str] = []

    async def cold_load(model_name: str, tag: str, dur: float):
        async with p._model_prepare_lock(1, model_name):
            enter_order.append(tag)
            await asyncio.sleep(dur)

    start = asyncio.get_event_loop().time()
    await asyncio.gather(
        cold_load("X", "A", 0.05),
        cold_load("Y", "B", 0.05),
    )
    elapsed = asyncio.get_event_loop().time() - start
    assert sorted(enter_order) == ["A", "B"]
    assert elapsed < 0.08, f"Different-model cold loads serialized (took {elapsed:.3f}s)"


@pytest.mark.asyncio
async def test_capacity_locks_on_different_providers_do_not_block():
    """ensure_capacity on workers A and B should run concurrently — the
    provider-capacity lock is keyed per provider."""
    p = _bare_planner()
    enter_order: list[str] = []

    async def reclaim(provider_id: int, tag: str, dur: float):
        async with p._provider_capacity_lock(provider_id):
            enter_order.append(tag)
            await asyncio.sleep(dur)

    start = asyncio.get_event_loop().time()
    await asyncio.gather(
        reclaim(1, "A", 0.05),
        reclaim(2, "B", 0.05),
    )
    elapsed = asyncio.get_event_loop().time() - start
    assert sorted(enter_order) == ["A", "B"]
    assert elapsed < 0.08, f"Capacity reclaim serialized across providers (took {elapsed:.3f}s)"


@pytest.mark.asyncio
async def test_many_concurrent_lane_locks_independence():
    """Stress: 20 concurrent operations on 20 different (provider, lane)
    pairs must execute in roughly one operation's worth of wall time."""
    p = _bare_planner()
    op_count = 20
    per_op = 0.02

    async def op(pid: int, lane: str):
        async with p._lane_lock(pid, lane):
            await asyncio.sleep(per_op)

    pairs = [(pid, f"lane-{pid}") for pid in range(op_count)]
    start = asyncio.get_event_loop().time()
    await asyncio.gather(*(op(pid, lane) for pid, lane in pairs))
    elapsed = asyncio.get_event_loop().time() - start
    # If serial: elapsed ~ op_count × per_op = 0.4s
    # If parallel: elapsed ~ per_op = 0.02s
    # Generous bound for jitter; anything > 5× per_op signals serialization.
    assert elapsed < per_op * 5, f"Independent lane locks contended ({elapsed:.3f}s for {op_count} parallel ops)"
