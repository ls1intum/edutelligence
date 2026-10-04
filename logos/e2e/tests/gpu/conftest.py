"""Tier 1 fixtures: a lane driver bound to the simulated machine."""

from __future__ import annotations

import pytest
from harness import lane as lane_harness

pytestmark = pytest.mark.gpu_sim


@pytest.fixture(autouse=True)
def fresh_cache_recovery_ledger():
    """Clear the process-global reactive-cache-recovery ledger between tests.

    The worker caps reactive purges at one per (model, hour) and keeps that
    ledger at module scope on purpose — it has to survive the lane manager
    recreating handles. Inside a test session that means the first test to
    trigger a purge blocks every later one for the same model, so each test
    would be measuring the rate limiter instead of what it asked about.

    The cap itself is covered directly by
    ``test_repeat_poisoning_within_the_hour_is_not_purged_again``.
    """
    from logos_worker_node import vllm_process

    vllm_process._last_reactive_cache_recovery.clear()
    yield
    vllm_process._last_reactive_cache_recovery.clear()


@pytest.fixture
def cache_root(tmp_path):
    """Persistent-cache root for the lane under test.

    Every cache the worker writes (HF, vLLM compile, inductor, FlashInfer)
    hangs off this one directory, so a test can inspect exactly what a purge
    removed and what it left alone.
    """
    root = tmp_path / "worker-state"
    (root / "models").mkdir(parents=True, exist_ok=True)
    (root / "cache").mkdir(parents=True, exist_ok=True)
    return root


@pytest.fixture
def lane(cache_root):
    """Factory for lane handles; every one is torn down at test end."""

    def _lane(**kwargs):
        return lane_harness.lane(cache_root, **kwargs)

    return _lane
