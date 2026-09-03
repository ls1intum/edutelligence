"""Tests for LogosNodeRuntimeRegistry → LatencyStore ingestion path.

Covers cold-load and wake-from-sleep timing propagation from worker lane
status dicts into the LatencyStore via _absorb_latency_observations.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

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
# Decode-only TTFT path (TPOT histogram → record_ttft)
# ---------------------------------------------------------------------------


def _tpot_histogram() -> dict:
    return {"0.05": 5, "0.1": 9, "0.2": 10, "+Inf": 10}


class TestDecodeOnlyTtftIngestion:
    """record_ttft must receive the TPOT P50, not the full TTFT, so that
    learned_ttft in ETTFT is the decode-only first-token time."""

    def _lane_with_tpot(self, model: str = "test-model", tpot_hist=None) -> dict:
        return {"model": model, "backend_metrics": {"tpot_histogram": tpot_hist or _tpot_histogram()}}

    def test_tpot_p50_recorded_as_ttft(self):
        store = MagicMock()
        reg = _make_registry(store)
        reg._absorb_latency_observations(5, _runtime([self._lane_with_tpot()]))
        # P50 of {0.05:5, 0.1:9, 0.2:10, +Inf:10} → 5th observation is ≤ 0.05
        # total=10, target=5.0; bucket 0.05 has count 5 which equals target → 0.05s
        store.record_ttft.assert_called_once_with("test-model", 5, pytest.approx(0.05))

    def test_empty_tpot_histogram_skips_record_ttft(self):
        store = MagicMock()
        reg = _make_registry(store)
        reg._absorb_latency_observations(5, _runtime([self._lane_with_tpot(tpot_hist={})]))
        store.record_ttft.assert_not_called()

    def test_missing_tpot_histogram_skips_record_ttft(self):
        store = MagicMock()
        reg = _make_registry(store)
        reg._absorb_latency_observations(5, _runtime([_lane()]))
        store.record_ttft.assert_not_called()


# ---------------------------------------------------------------------------
# No latency store — absorb is skipped by the caller guard
# ---------------------------------------------------------------------------


class TestNoLatencyStore:
    def test_registry_without_store_has_none(self):
        reg = LogosNodeRuntimeRegistry()
        assert reg._latency_store is None


# ---------------------------------------------------------------------------
# Prefill ingestion path (last_prefill_s / last_prefill_tokens from worker)
# ---------------------------------------------------------------------------


class TestPrefillIngestion:
    def _lane_with_prefill(self, model: str = "test-model", prefill_s=1.5, prefill_tokens=300, **kwargs) -> dict:
        return {
            "model": model,
            "backend_metrics": {"last_prefill_s": prefill_s, "last_prefill_tokens": prefill_tokens, **kwargs},
        }

    def test_prefill_observation_reaches_record_prefill(self):
        store = MagicMock()
        reg = _make_registry(store)
        reg._absorb_latency_observations(7, _runtime([self._lane_with_prefill()]))
        store.record_prefill.assert_called_once_with("test-model", 7, 1.5, 300)

    def test_prefill_provider_id_forwarded(self):
        store = MagicMock()
        reg = _make_registry(store)
        reg._absorb_latency_observations(42, _runtime([self._lane_with_prefill(prefill_s=2.0, prefill_tokens=500)]))
        store.record_prefill.assert_called_once_with("test-model", 42, 2.0, 500)

    def test_prefill_tokens_zero_rejected(self):
        store = MagicMock()
        reg = _make_registry(store)
        reg._absorb_latency_observations(1, _runtime([self._lane_with_prefill(prefill_tokens=0)]))
        store.record_prefill.assert_not_called()

    def test_prefill_tokens_fractional_rejected(self):
        store = MagicMock()
        reg = _make_registry(store)
        reg._absorb_latency_observations(1, _runtime([self._lane_with_prefill(prefill_tokens=1.5)]))
        store.record_prefill.assert_not_called()

    def test_prefill_s_infinite_rejected(self):
        store = MagicMock()
        reg = _make_registry(store)
        reg._absorb_latency_observations(1, _runtime([self._lane_with_prefill(prefill_s=float("inf"))]))
        store.record_prefill.assert_not_called()

    def test_prefill_tokens_infinite_rejected(self):
        store = MagicMock()
        reg = _make_registry(store)
        reg._absorb_latency_observations(1, _runtime([self._lane_with_prefill(prefill_tokens=float("inf"))]))
        store.record_prefill.assert_not_called()

    def test_prefill_missing_fields_not_called(self):
        store = MagicMock()
        reg = _make_registry(store)
        reg._absorb_latency_observations(1, _runtime([_lane()]))
        store.record_prefill.assert_not_called()

    def test_prefill_none_fields_not_called(self):
        store = MagicMock()
        reg = _make_registry(store)
        reg._absorb_latency_observations(1, _runtime([self._lane_with_prefill(prefill_s=None, prefill_tokens=300)]))
        store.record_prefill.assert_not_called()
