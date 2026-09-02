"""Tests for LogosNodeRuntimeRegistry → LatencyStore ingestion path.

Covers cold-load and wake-from-sleep timing propagation from worker lane
status dicts into the LatencyStore via _absorb_latency_observations.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from logos.logosnode_registry import LogosNodeRuntimeRegistry
from logos.pipeline.ettft_estimator import ReadinessTier


def _make_registry(latency_store):
    return LogosNodeRuntimeRegistry(latency_store=latency_store)


def _runtime(lanes: list[dict]) -> dict:
    return {"lanes": lanes}


def _lane(model: str = "test-model", **kwargs) -> dict:
    return {"model": model, **kwargs}


# ---------------------------------------------------------------------------
# Cold-load path
# ---------------------------------------------------------------------------


class TestColdLoadIngestion:
    def test_cold_load_recorded_as_cold_tier(self):
        store = MagicMock()
        reg = _make_registry(store)
        reg._absorb_latency_observations(1, _runtime([_lane(last_cold_load_s=30.0)]))
        store.record_overhead.assert_any_call("test-model", 1, ReadinessTier.COLD, 30.0)

    def test_cold_load_zero_ignored(self):
        store = MagicMock()
        reg = _make_registry(store)
        reg._absorb_latency_observations(1, _runtime([_lane(last_cold_load_s=0.0)]))
        for c in store.record_overhead.call_args_list:
            assert c.args[2] != ReadinessTier.COLD

    def test_cold_load_none_ignored(self):
        store = MagicMock()
        reg = _make_registry(store)
        reg._absorb_latency_observations(1, _runtime([_lane(last_cold_load_s=None)]))
        store.record_overhead.assert_not_called()


# ---------------------------------------------------------------------------
# Wake-from-sleep path
# ---------------------------------------------------------------------------


class TestWakeFromSleepIngestion:
    def test_wake_recorded_as_sleeping_tier(self):
        store = MagicMock()
        reg = _make_registry(store)
        reg._absorb_latency_observations(2, _runtime([_lane(last_wake_from_sleep_s=5.0)]))
        store.record_overhead.assert_any_call("test-model", 2, ReadinessTier.SLEEPING, 5.0)

    def test_wake_zero_ignored(self):
        store = MagicMock()
        reg = _make_registry(store)
        reg._absorb_latency_observations(2, _runtime([_lane(last_wake_from_sleep_s=0.0)]))
        for c in store.record_overhead.call_args_list:
            assert c.args[2] != ReadinessTier.SLEEPING

    def test_wake_none_ignored(self):
        store = MagicMock()
        reg = _make_registry(store)
        reg._absorb_latency_observations(2, _runtime([_lane(last_wake_from_sleep_s=None)]))
        store.record_overhead.assert_not_called()

    def test_both_cold_and_wake_recorded(self):
        store = MagicMock()
        reg = _make_registry(store)
        reg._absorb_latency_observations(
            3,
            _runtime([_lane(last_cold_load_s=40.0, last_wake_from_sleep_s=6.0)]),
        )
        store.record_overhead.assert_any_call("test-model", 3, ReadinessTier.COLD, 40.0)
        store.record_overhead.assert_any_call("test-model", 3, ReadinessTier.SLEEPING, 6.0)

    def test_provider_id_forwarded_correctly(self):
        store = MagicMock()
        reg = _make_registry(store)
        reg._absorb_latency_observations(99, _runtime([_lane(last_wake_from_sleep_s=8.0)]))
        store.record_overhead.assert_called_once_with("test-model", 99, ReadinessTier.SLEEPING, 8.0)


# ---------------------------------------------------------------------------
# No latency store — absorb is skipped by the caller guard
# ---------------------------------------------------------------------------


class TestNoLatencyStore:
    def test_registry_without_store_has_none(self):
        reg = LogosNodeRuntimeRegistry()
        assert reg._latency_store is None
