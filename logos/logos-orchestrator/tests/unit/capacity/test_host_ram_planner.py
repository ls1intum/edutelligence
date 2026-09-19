"""Tests for the planner's host-RAM headroom precheck.

The precheck reads the worker's reported host_memory.available_mb from the
runtime snapshot, subtracts in-flight HostRamLedger commitments and the
HOST_RAM_SAFETY_MARGIN_MB, and compares against the projected lane footprint.
It is a pure gate — it does not stop existing lanes.
"""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock

# Only stub prometheus when the real package (or its .core submodule) is
# unavailable — a bare ModuleType stub shadows an installed package and
# breaks ``from prometheus_client.core import Metric``.
try:
    import prometheus_client.core  # noqa: F401
except ImportError:
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

        _prom_stub.Counter = _MetricStub
        _prom_stub.Gauge = _MetricStub
        _prom_stub.Histogram = _MetricStub
        _prom_stub.Summary = _MetricStub
        _prom_stub.CollectorRegistry = MagicMock
        _prom_stub.REGISTRY = MagicMock()
        _prom_stub.CONTENT_TYPE_LATEST = "text/plain"
        _prom_stub.generate_latest = lambda *a, **kw: b""
        sys.modules["prometheus_client"] = _prom_stub

from logos import CapacityPlanner  # noqa: E402
from logos.capacity.host_ram_ledger import HostRamLedger  # noqa: E402
from logos.sdi.models import CapacityPlanAction  # noqa: E402


def _bare_planner(snapshot: dict | None = None) -> CapacityPlanner:
    """Build a planner with only the fields the precheck touches."""
    planner = CapacityPlanner.__new__(CapacityPlanner)
    planner._host_ram_ledger = HostRamLedger()
    registry = MagicMock()
    registry.peek_runtime_snapshot.return_value = snapshot
    planner._registry = registry
    return planner


def _snapshot_with_host_memory(available_mb: float | None) -> dict:
    """Build a minimal snapshot dict shaped like the master ingests."""
    host_memory: dict = {"source": "proc-meminfo"}
    if available_mb is not None:
        host_memory["available_mb"] = available_mb
    return {"runtime": {"host_memory": host_memory, "lanes": []}}


def test_precheck_ok_when_projected_fits_with_margin():
    """50 GiB load against 100 GiB available passes (margin is ~4 GiB)."""
    p = _bare_planner(_snapshot_with_host_memory(100_000.0))
    ok, eff, deficit = p._check_host_ram_headroom_for_cold_load(
        provider_id=1,
        loading_model="m",
        projected_host_ram_mb=50_000.0,
    )
    assert ok is True
    assert deficit == 0.0
    assert eff == 100_000.0 - p.HOST_RAM_SAFETY_MARGIN_MB


def test_precheck_denies_when_projected_exceeds_available():
    """The deioma scenario: 48 GiB checkpoint vs ~15 GiB available."""
    p = _bare_planner(_snapshot_with_host_memory(15_000.0))
    ok, eff, deficit = p._check_host_ram_headroom_for_cold_load(
        provider_id=1,
        loading_model="gemma-4-26B",
        projected_host_ram_mb=48_000.0,
    )
    assert ok is False
    assert deficit > 0


def test_precheck_accounts_for_ledger_commitments():
    """An in-flight 60 GiB load reduces the effective available."""
    p = _bare_planner(_snapshot_with_host_memory(100_000.0))
    p._host_ram_ledger.reserve(1, "in-flight", "load", host_ram_mb=60_000.0)
    ok, eff, deficit = p._check_host_ram_headroom_for_cold_load(
        provider_id=1,
        loading_model="m2",
        projected_host_ram_mb=50_000.0,
    )
    # eff = 100k - 60k - margin = ~36k; 50k load is denied.
    assert ok is False
    assert deficit > 0


def test_precheck_fails_open_when_worker_lacks_host_memory():
    """Pre-upgrade worker has no host_memory key → precheck returns OK."""
    p = _bare_planner({"runtime": {"lanes": []}})
    ok, eff, deficit = p._check_host_ram_headroom_for_cold_load(
        provider_id=1,
        loading_model="m",
        projected_host_ram_mb=999_999.0,
    )
    assert ok is True
    assert deficit == 0.0


def test_precheck_fails_open_when_host_memory_source_is_unavailable():
    """Worker that read /proc/meminfo and got nothing also fails open."""
    p = _bare_planner({"runtime": {"host_memory": {"source": "unavailable"}}})
    ok, _, _ = p._check_host_ram_headroom_for_cold_load(
        provider_id=1,
        loading_model="m",
        projected_host_ram_mb=10_000.0,
    )
    assert ok is True


def test_precheck_does_not_mutate_ledger():
    """The precheck is pure — no reservation must be created."""
    p = _bare_planner(_snapshot_with_host_memory(100_000.0))
    p._check_host_ram_headroom_for_cold_load(
        provider_id=1,
        loading_model="m",
        projected_host_ram_mb=50_000.0,
    )
    assert p._host_ram_ledger.get_committed_mb(1) == 0.0


def test_lane_host_ram_from_snapshot_returns_measured_value():
    p = _bare_planner(
        {
            "runtime": {
                "host_memory": {"source": "proc-meminfo", "available_mb": 50_000.0},
                "lanes": [
                    {"lane_id": "planner-foo", "host_ram_mb": 12_345.0},
                    {"lane_id": "planner-bar", "host_ram_mb": 6_789.0},
                ],
            },
        }
    )
    assert p._lane_host_ram_from_snapshot(1, "planner-foo") == 12_345.0
    assert p._lane_host_ram_from_snapshot(1, "planner-bar") == 6_789.0
    assert p._lane_host_ram_from_snapshot(1, "planner-missing") == 0.0


# ---------------------------------------------------------------------------
# Sleeping costs host RAM for as long as it lasts
#
# sleep_l1 relocates a lane's weights to host RAM rather than dropping them,
# so the memory is spoken for until the lane wakes or is stopped. Only the
# transient peak *during* the call was ever checked, which answers "can this
# sleep complete" and nothing about what it leaves behind — so a worker could
# pass the check for lane after lane and still end up with its RAM gone.
# ---------------------------------------------------------------------------


def _profile(**kwargs) -> SimpleNamespace:
    base = {
        "sleep_l1_transient_host_ram_mb": None,
        "sleep_l2_transient_host_ram_mb": None,
        "host_ram_residual_mb": None,
        "host_ram_mb": None,
        "disk_size_bytes": None,
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_sleep_precheck_counts_what_the_sleep_leaves_behind():
    """A cheap transfer with an expensive resting footprint: 2 GB moves, 40 GB
    stays. Judging it on the transient alone waves it through and the host is
    40 GB poorer with nothing recording it."""
    p = _bare_planner(_snapshot_with_host_memory(30_000.0))

    ok, _eff, required = p._check_host_ram_headroom_for_sleep(
        1, 1, _profile(sleep_l1_transient_host_ram_mb=2_000.0, host_ram_residual_mb=40_000.0)
    )

    assert ok is False
    assert required >= 40_000.0


def test_sleep_precheck_still_denies_on_the_transient_alone():
    """The original guard: the peak during the call has to fit too, whatever
    the lane settles at afterwards."""
    p = _bare_planner(_snapshot_with_host_memory(10_000.0))

    ok, _eff, required = p._check_host_ram_headroom_for_sleep(
        1, 2, _profile(sleep_l2_transient_host_ram_mb=60_000.0, host_ram_residual_mb=1_000.0)
    )

    assert ok is False
    assert required >= 60_000.0


def test_sleep_precheck_passes_when_the_host_can_afford_a_resident_sleeper():
    p = _bare_planner(_snapshot_with_host_memory(200_000.0))

    ok, _eff, _required = p._check_host_ram_headroom_for_sleep(
        1, 1, _profile(sleep_l1_transient_host_ram_mb=2_000.0, host_ram_residual_mb=40_000.0)
    )

    assert ok is True


def test_sleep_precheck_without_a_residency_measurement_is_unchanged():
    """Workers that predate the field, and models that have never slept here,
    keep the transient-only behaviour rather than being blocked."""
    p = _bare_planner(_snapshot_with_host_memory(30_000.0))

    ok, _eff, required = p._check_host_ram_headroom_for_sleep(1, 1, _profile(sleep_l1_transient_host_ram_mb=2_000.0))

    assert ok is True
    assert required == p.HOST_RAM_SAFETY_MARGIN_MB + 2_000.0


# ---------------------------------------------------------------------------
# Sticky EngineCore host-RAM growth (#1061)
#
# Long-lived awake lanes can hold tens of GB of host shm beyond the calibrated
# footprint. Sleep→wake does not clear that ceiling, so cold-load projections
# and sleep residency must prefer live / high-water marks over lean profiles.
# ---------------------------------------------------------------------------


def test_cold_estimate_uses_live_same_model_ceiling_over_lean_profile():
    """A fresh replica of a model that already has a sticky-heavy sibling must
    be gated against that live ceiling, not only disk/profile size."""
    p = _bare_planner(
        {
            "runtime": {
                "host_memory": {"source": "proc-meminfo", "available_mb": 200_000.0},
                "lanes": [
                    {
                        "lane_id": "old",
                        "model": "Qwen/Qwen3.8-27B",
                        "host_ram_mb": 80_000.0,
                        "sleep_state": "awake",
                        "runtime_state": "loaded",
                    },
                    {
                        "lane_id": "new",
                        "model": "Qwen/Qwen3.8-27B",
                        "host_ram_mb": 5_500.0,
                        "sleep_state": "awake",
                        "runtime_state": "loaded",
                    },
                    {
                        "lane_id": "other",
                        "model": "other/model",
                        "host_ram_mb": 90_000.0,
                        "sleep_state": "awake",
                        "runtime_state": "loaded",
                    },
                ],
            },
        }
    )
    profile = _profile(host_ram_mb=6_000.0, disk_size_bytes=50_000 * 1024 * 1024)

    projected = p._estimate_lane_host_ram_mb(
        1,
        "cold-lane",
        "Qwen/Qwen3.8-27B",
        profile,
        runtime_state="cold",
    )

    assert projected == 80_000.0


def test_cold_estimate_falls_back_to_profile_when_no_siblings():
    p = _bare_planner(_snapshot_with_host_memory(200_000.0))
    profile = _profile(host_ram_mb=12_000.0)

    projected = p._estimate_lane_host_ram_mb(
        1,
        "cold-lane",
        "Qwen/Qwen3.8-27B",
        profile,
        runtime_state="cold",
    )

    assert projected == 12_000.0


def test_cold_estimate_ignores_sleeping_sibling_host_ram():
    """Sleeping PSS includes weight backups — not the awake sticky ceiling."""
    p = _bare_planner(
        {
            "runtime": {
                "host_memory": {"source": "proc-meminfo", "available_mb": 200_000.0},
                "lanes": [
                    {
                        "lane_id": "asleep",
                        "model": "Qwen/Qwen3.8-27B",
                        "host_ram_mb": 80_000.0,
                        "sleep_state": "sleeping",
                        "runtime_state": "sleeping",
                    },
                    {
                        "lane_id": "awake",
                        "model": "Qwen/Qwen3.8-27B",
                        "host_ram_mb": 6_000.0,
                        "sleep_state": "awake",
                        "runtime_state": "loaded",
                    },
                ],
            },
        }
    )
    profile = _profile(host_ram_mb=5_000.0)

    projected = p._estimate_lane_host_ram_mb(
        1,
        "cold-lane",
        "Qwen/Qwen3.8-27B",
        profile,
        runtime_state="cold",
    )

    assert projected == 6_000.0


def test_sleep_precheck_does_not_double_count_live_sticky_pss():
    """Live sticky PSS is already in MemAvailable — charging it again as
    required residency would falsely escalate every heavy lane to stop."""
    p = _bare_planner(
        {
            "runtime": {
                "host_memory": {"source": "proc-meminfo", "available_mb": 50_000.0},
                "lanes": [
                    {"lane_id": "heavy", "model": "Qwen/Qwen3.8-27B", "host_ram_mb": 70_000.0},
                ],
            },
        }
    )

    ok, _eff, required = p._check_host_ram_headroom_for_sleep(
        1,
        1,
        _profile(sleep_l1_transient_host_ram_mb=2_000.0, host_ram_residual_mb=8_000.0),
        lane_id="heavy",
    )

    assert ok is True
    assert required == p.HOST_RAM_SAFETY_MARGIN_MB + 2_000.0


def test_sleep_precheck_charges_incremental_weight_relocation_beyond_live():
    """Lean live hold + large residual → sleep still needs room for weights."""
    p = _bare_planner(
        {
            "runtime": {
                "host_memory": {"source": "proc-meminfo", "available_mb": 30_000.0},
                "lanes": [
                    {"lane_id": "lean", "model": "Qwen/Qwen3.8-27B", "host_ram_mb": 5_000.0},
                ],
            },
        }
    )

    ok, _eff, required = p._check_host_ram_headroom_for_sleep(
        1,
        1,
        _profile(sleep_l1_transient_host_ram_mb=2_000.0, host_ram_residual_mb=40_000.0),
        lane_id="lean",
    )

    # incremental = 40k - 5k = 35k; transient 2k → required = margin + 35k
    assert ok is False
    assert required == p.HOST_RAM_SAFETY_MARGIN_MB + 35_000.0


async def test_sleep_action_escalates_to_stop_when_incremental_host_ram_does_not_fit():
    """Executor must turn sleep_l1 into stop when the host-RAM gate denies."""
    profile = _profile(
        sleep_l1_transient_host_ram_mb=2_000.0,
        host_ram_residual_mb=40_000.0,
        sleeping_residual_mb=1_000.0,
        loaded_vram_mb=80_000.0,
        engine="vllm",
        base_residency_mb=40_000.0,
    )
    p = _bare_planner(
        {
            "runtime": {
                "host_memory": {"source": "proc-meminfo", "available_mb": 30_000.0},
                "lanes": [
                    {"lane_id": "lean", "model": "Qwen/Qwen3.8-27B", "host_ram_mb": 5_000.0},
                ],
            },
        }
    )
    p._facade = MagicMock()
    p._facade.get_provider_name.return_value = "worker-a"
    p._safe_get_profiles = MagicMock(return_value={"Qwen/Qwen3.8-27B": profile})
    p._safe_get_capacity = MagicMock(return_value=None)
    p._lane_gpu_devices_str = MagicMock(return_value=None)
    p._get_per_gpu_free = MagicMock(return_value=None)
    p._release_vram = MagicMock()
    p._vram_ledger = MagicMock()

    escalated: list[CapacityPlanAction] = []

    async def _capture_confirmation(action, timeout_seconds=60.0):
        escalated.append(action)
        return True

    p._execute_action_with_confirmation = _capture_confirmation

    sleep_action = CapacityPlanAction(
        action="sleep_l1",
        provider_id=1,
        lane_id="lean",
        model_name="Qwen/Qwen3.8-27B",
        reason="reclaim",
    )
    ok = await CapacityPlanner._execute_action_core(p, sleep_action, timeout_seconds=5.0)

    assert ok is True
    assert len(escalated) == 1
    assert escalated[0].action == "stop"
    assert escalated[0].lane_id == "lean"
    assert escalated[0].bypass_load_cooldown is True
    assert "host RAM headroom too low" in escalated[0].reason
