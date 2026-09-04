"""Unit tests for logos.pipeline.latency_store."""

from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from logos.pipeline.ettft_estimator import OVERHEAD_COLD_S, OVERHEAD_SLEEPING_S, RECLAIM_IDLE_EVICT_S, ReadinessTier
from logos.pipeline.latency_store import _MIN_PLAUSIBLE_S, LatencyStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_store(**kwargs) -> LatencyStore:
    return LatencyStore(**kwargs)


# ---------------------------------------------------------------------------
# record_overhead / get_overhead_s
# ---------------------------------------------------------------------------


class TestRecordOverhead:
    def test_first_observation_seeds_ewma_directly(self):
        store = make_store()
        store.record_overhead("m", 1, ReadinessTier.COLD, 30.0)
        assert store.get_overhead_s("m", 1, ReadinessTier.COLD) == pytest.approx(30.0)

    def test_second_observation_applies_alpha(self):
        store = make_store(alpha=0.2)
        store.record_overhead("m", 1, ReadinessTier.COLD, 40.0)
        store.record_overhead("m", 1, ReadinessTier.COLD, 20.0)
        expected = 0.2 * 20.0 + 0.8 * 40.0  # = 36.0
        assert store.get_overhead_s("m", 1, ReadinessTier.COLD) == pytest.approx(expected)

    def test_observation_below_min_plausible_is_ignored(self):
        store = make_store()
        store.record_overhead("m", 1, ReadinessTier.COLD, 40.0)
        store.record_overhead("m", 1, ReadinessTier.COLD, _MIN_PLAUSIBLE_S - 0.01)
        assert store.get_overhead_s("m", 1, ReadinessTier.COLD) == pytest.approx(40.0)

    def test_warm_tier_is_never_stored(self):
        store = make_store()
        store.record_overhead("m", 1, ReadinessTier.WARM, 999.0)
        assert store.get_overhead_s("m", 1, ReadinessTier.WARM) == 0.0

    def test_busy_tier_is_never_stored(self):
        store = make_store()
        store.record_overhead("m", 1, ReadinessTier.BUSY, 999.0)
        assert store.get_overhead_s("m", 1, ReadinessTier.BUSY) == 0.0

    def test_unavailable_tier_is_never_stored_and_returns_inf(self):
        store = make_store()
        store.record_overhead("m", 1, ReadinessTier.UNAVAILABLE, 999.0)
        assert store.get_overhead_s("m", 1, ReadinessTier.UNAVAILABLE) == float("inf")

    def test_keyed_by_model_provider_tier(self):
        store = make_store()
        store.record_overhead("a", 1, ReadinessTier.COLD, 10.0)
        store.record_overhead("a", 2, ReadinessTier.COLD, 20.0)
        store.record_overhead("b", 1, ReadinessTier.COLD, 30.0)
        store.record_overhead("a", 1, ReadinessTier.SLEEPING, 5.0)
        assert store.get_overhead_s("a", 1, ReadinessTier.COLD) == pytest.approx(10.0)
        assert store.get_overhead_s("a", 2, ReadinessTier.COLD) == pytest.approx(20.0)
        assert store.get_overhead_s("b", 1, ReadinessTier.COLD) == pytest.approx(30.0)
        assert store.get_overhead_s("a", 1, ReadinessTier.SLEEPING) == pytest.approx(5.0)

    def test_observation_count(self):
        store = make_store()
        assert store.get_observation_count("m", 1, ReadinessTier.COLD) == 0
        store.record_overhead("m", 1, ReadinessTier.COLD, 10.0)
        assert store.get_observation_count("m", 1, ReadinessTier.COLD) == 1
        store.record_overhead("m", 1, ReadinessTier.COLD, 20.0)
        assert store.get_observation_count("m", 1, ReadinessTier.COLD) == 2


# ---------------------------------------------------------------------------
# Prior computation (fallback when no learned value exists)
# ---------------------------------------------------------------------------


class TestPrior:
    def test_cold_prior_uses_vram_and_bandwidth(self):
        store = make_store(io_bandwidth_mb_s=500.0)
        # 50 000 MB / 500 MB/s = 100 s
        prior = store.get_overhead_s("m", 1, ReadinessTier.COLD, model_vram_mb=50_000.0)
        assert prior == pytest.approx(100.0)

    def test_cold_prior_divides_by_tp_size(self):
        store = make_store(io_bandwidth_mb_s=1000.0)
        # 80 000 MB / 4 / 1000 MB/s = 20 s
        prior = store.get_overhead_s("m", 1, ReadinessTier.COLD, model_vram_mb=80_000.0, tp_size=4)
        assert prior == pytest.approx(20.0)

    def test_cold_prior_falls_back_to_constant_when_vram_unknown(self):
        store = make_store()
        prior = store.get_overhead_s("m", 1, ReadinessTier.COLD, model_vram_mb=0.0)
        assert prior == pytest.approx(OVERHEAD_COLD_S)

    def test_cold_reclaim_prior_adds_reclaim_constant(self):
        store = make_store(io_bandwidth_mb_s=500.0)
        cold_prior = 50_000.0 / 500.0  # 100 s
        prior = store.get_overhead_s("m", 1, ReadinessTier.COLD_RECLAIM, model_vram_mb=50_000.0)
        assert prior == pytest.approx(cold_prior + RECLAIM_IDLE_EVICT_S)

    def test_sleeping_prior_is_static_constant(self):
        store = make_store()
        prior = store.get_overhead_s("m", 1, ReadinessTier.SLEEPING)
        assert prior == pytest.approx(OVERHEAD_SLEEPING_S)

    def test_sleeping_reclaim_prior_adds_reclaim_constant(self):
        store = make_store()
        prior = store.get_overhead_s("m", 1, ReadinessTier.SLEEPING_RECLAIM)
        assert prior == pytest.approx(OVERHEAD_SLEEPING_S + RECLAIM_IDLE_EVICT_S)

    def test_learned_value_overrides_prior(self):
        store = make_store(io_bandwidth_mb_s=500.0)
        store.record_overhead("m", 1, ReadinessTier.COLD, 55.0)
        result = store.get_overhead_s("m", 1, ReadinessTier.COLD, model_vram_mb=50_000.0)
        # Learned value (55.0) should win over the 100 s prior.
        assert result == pytest.approx(55.0)


# ---------------------------------------------------------------------------
# record_ttft / get_ttft_s
# ---------------------------------------------------------------------------


class TestTtft:
    def test_returns_none_before_any_observation(self):
        store = make_store()
        assert store.get_ttft_s("m", 1) is None

    def test_first_observation_seeds_directly(self):
        store = make_store()
        store.record_ttft("m", 1, 1.5)
        assert store.get_ttft_s("m", 1) == pytest.approx(1.5)

    def test_ewma_update(self):
        store = make_store(alpha=0.2)
        store.record_ttft("m", 1, 2.0)
        store.record_ttft("m", 1, 1.0)
        expected = 0.2 * 1.0 + 0.8 * 2.0  # 1.8
        assert store.get_ttft_s("m", 1) == pytest.approx(expected)

    def test_non_positive_or_nan_ignored(self):
        store = make_store()
        store.record_ttft("m", 1, 2.0)
        store.record_ttft("m", 1, 0.0)
        store.record_ttft("m", 1, float("nan"))
        assert store.get_ttft_s("m", 1) == pytest.approx(2.0)

    def test_sub_100ms_accepted(self):
        # TPOT P50 values such as 0.05 s must not be filtered by the load-time guard.
        store = make_store()
        store.record_ttft("m", 1, 0.05)
        assert store.get_ttft_s("m", 1) == pytest.approx(0.05)

    def test_keyed_by_model_and_provider(self):
        store = make_store()
        store.record_ttft("a", 1, 1.0)
        store.record_ttft("b", 1, 3.0)
        store.record_ttft("a", 2, 9.0)
        assert store.get_ttft_s("a", 1) == pytest.approx(1.0)
        assert store.get_ttft_s("b", 1) == pytest.approx(3.0)
        assert store.get_ttft_s("a", 2) == pytest.approx(9.0)


# ---------------------------------------------------------------------------
# record_e2e_latency / get_e2e_latency_s
# ---------------------------------------------------------------------------


class TestE2eLatency:
    def test_returns_none_before_any_observation(self):
        store = make_store()
        assert store.get_e2e_latency_s("m", 1) is None

    def test_first_observation_seeds_directly(self):
        store = make_store()
        store.record_e2e_latency("m", 1, 5.0)
        assert store.get_e2e_latency_s("m", 1) == pytest.approx(5.0)

    def test_ewma_update(self):
        store = make_store(alpha=0.2)
        store.record_e2e_latency("m", 1, 10.0)
        store.record_e2e_latency("m", 1, 5.0)
        expected = 0.2 * 5.0 + 0.8 * 10.0  # 9.0
        assert store.get_e2e_latency_s("m", 1) == pytest.approx(expected)

    def test_keyed_by_model_and_provider(self):
        store = make_store()
        store.record_e2e_latency("m", 1, 5.0)
        store.record_e2e_latency("m", 2, 12.0)
        assert store.get_e2e_latency_s("m", 1) == pytest.approx(5.0)
        assert store.get_e2e_latency_s("m", 2) == pytest.approx(12.0)


# ---------------------------------------------------------------------------
# DB persistence
# ---------------------------------------------------------------------------


def _make_db_factory(rows=None, upsert_mock=None):
    """Return a db_factory that yields a mock DBManager with the given rows."""
    db_mock = MagicMock()
    db_mock.get_all_latency_observations.return_value = rows or []
    if upsert_mock is not None:
        db_mock.upsert_latency_observation = upsert_mock

    @contextmanager
    def factory():
        yield db_mock

    return factory, db_mock


class TestPersistence:
    def test_loads_overhead_from_db_on_init(self):
        rows = [("model-a", 1, "cold", 42.0, 5)]
        factory, _ = _make_db_factory(rows)
        store = LatencyStore(db_factory=factory)
        assert store.get_overhead_s("model-a", 1, ReadinessTier.COLD) == pytest.approx(42.0)
        assert store.get_observation_count("model-a", 1, ReadinessTier.COLD) == 5

    def test_loads_ttft_from_db_on_init(self):
        rows = [("model-a", 5, "ttft", 1.5, 10)]
        factory, _ = _make_db_factory(rows)
        store = LatencyStore(db_factory=factory)
        assert store.get_ttft_s("model-a", 5) == pytest.approx(1.5)

    def test_loads_e2e_from_db_on_init(self):
        rows = [("model-a", 5, "e2e", 8.0, 3)]
        factory, _ = _make_db_factory(rows)
        store = LatencyStore(db_factory=factory)
        assert store.get_e2e_latency_s("model-a", 5) == pytest.approx(8.0)

    def test_unknown_tier_in_db_is_skipped(self):
        rows = [("model-a", 1, "unknown_tier_xyz", 99.0, 1)]
        factory, _ = _make_db_factory(rows)
        store = LatencyStore(db_factory=factory)
        # Should not crash; no overhead stored
        assert store.get_observation_count("model-a", 1, ReadinessTier.COLD) == 0

    def test_record_overhead_calls_upsert(self):
        upsert = MagicMock()
        factory, _ = _make_db_factory(upsert_mock=upsert)
        store = LatencyStore(db_factory=factory)
        store.record_overhead("m", 2, ReadinessTier.SLEEPING, 3.5)
        upsert.assert_called_once_with("m", 2, "sleeping", pytest.approx(3.5), 1)

    def test_record_ttft_calls_upsert(self):
        upsert = MagicMock()
        factory, _ = _make_db_factory(upsert_mock=upsert)
        store = LatencyStore(db_factory=factory)
        store.record_ttft("m", 3, 2.0)
        upsert.assert_called_once_with("m", 3, "ttft", pytest.approx(2.0), 1)

    def test_record_e2e_calls_upsert(self):
        upsert = MagicMock()
        factory, _ = _make_db_factory(upsert_mock=upsert)
        store = LatencyStore(db_factory=factory)
        store.record_e2e_latency("m", 3, 5.0)
        upsert.assert_called_once_with("m", 3, "e2e", pytest.approx(5.0), 1)

    def test_no_db_factory_stays_in_memory(self):
        store = LatencyStore()  # no db_factory
        store.record_overhead("m", 1, ReadinessTier.COLD, 30.0)
        assert store.get_overhead_s("m", 1, ReadinessTier.COLD) == pytest.approx(30.0)
