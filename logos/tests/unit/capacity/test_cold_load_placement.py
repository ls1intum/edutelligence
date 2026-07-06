"""Tests for `_pick_cold_load_placement` GPU-combo selection.

A lane is pinned to its GPUs for the lifetime of the process — a sleeping
vLLM lane cannot migrate — so placement must avoid co-locating with other
lanes when an equally feasible emptier GPU exists. The June 2026 deioma
incident: the embedding lane was packed onto GPU 0 next to half of
gpt-oss-120b (tp=2 on GPUs 0,2) while GPU 1 sat empty; every later wake of
the embedding then forced an eviction of gpt-oss.
"""

import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List
from unittest.mock import MagicMock

if "prometheus_client" not in sys.modules:
    import types

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

    _prom_stub = types.ModuleType("prometheus_client")
    _prom_stub.Counter = _MetricStub  # type: ignore[attr-defined]
    _prom_stub.Gauge = _MetricStub  # type: ignore[attr-defined]
    _prom_stub.Histogram = _MetricStub  # type: ignore[attr-defined]
    _prom_stub.Summary = _MetricStub  # type: ignore[attr-defined]
    _prom_stub.CollectorRegistry = MagicMock  # type: ignore[attr-defined]
    _prom_stub.REGISTRY = MagicMock()  # type: ignore[attr-defined]
    _prom_stub.CONTENT_TYPE_LATEST = "text/plain"  # type: ignore[attr-defined]
    _prom_stub.generate_latest = lambda *a, **kw: b""  # type: ignore[attr-defined]
    sys.modules["prometheus_client"] = _prom_stub

from logos.capacity.capacity_planner import CapacityPlanner  # noqa: E402
from logos.capacity.vram_ledger import VRAMLedger  # noqa: E402
from logos.sdi.models import LaneSchedulerSignals  # noqa: E402


@dataclass
class _MockProvider:
    provider_id: int
    name: str
    lanes: List[LaneSchedulerSignals] = field(default_factory=list)
    profiles: Dict[str, Any] = field(default_factory=dict)


class _MockFacade:
    def __init__(self, providers: List[_MockProvider]):
        self._providers = {p.provider_id: p for p in providers}

    def get_provider_name(self, provider_id: int) -> str:
        return self._providers[provider_id].name

    def get_scheduler_queue_depth_by_model_name(self, model_name: str, provider_id: int) -> int:
        return 0


def _lane(
    *,
    lane_id: str,
    model_name: str,
    sleep_state: str = "awake",
    gpu_devices: str = "0",
    effective_vram_mb: float = 20_000.0,
) -> LaneSchedulerSignals:
    return LaneSchedulerSignals(
        lane_id=lane_id,
        model_name=model_name,
        runtime_state="loaded",
        sleep_state=sleep_state,
        is_vllm=True,
        active_requests=0,
        queue_waiting=0.0,
        requests_running=0.0,
        gpu_cache_usage_percent=None,
        ttft_p95_seconds=0.0,
        e2e_latency_p50_seconds=0.0,
        effective_vram_mb=effective_vram_mb,
        num_parallel=0,
        gpu_devices=gpu_devices,
    )


def _planner(per_gpu_free: dict[int, float], lanes: List[LaneSchedulerSignals]) -> CapacityPlanner:
    provider = _MockProvider(provider_id=1, name="worker", lanes=lanes)
    registry = MagicMock()
    registry.peek_runtime_snapshot.return_value = {
        "runtime": {
            "lanes": [],
            "devices": {
                "devices": [
                    {"extra": {"index": gpu_id}, "memory_free_mb": free} for gpu_id, free in per_gpu_free.items()
                ]
            },
        }
    }
    planner = CapacityPlanner.__new__(CapacityPlanner)
    planner._facade = _MockFacade([provider])
    planner._registry = registry
    planner._vram_ledger = VRAMLedger()
    planner._replica_first_eviction = False
    planner._eviction_gate_v2 = True
    planner._stop_dedup_siblings = False
    planner._lane_loaded_at = {}
    planner._lane_idle_since = {}
    planner._lane_sleep_since = {}
    planner._lane_sleep_level = {}
    planner._load_cooldown_seconds = 0.0
    return planner


class TestColocationAwarePlacement:
    def test_prefers_empty_gpu_over_shared_one(self):
        """The deioma incident layout: identical feasibility on every GPU, but
        GPU 1 is empty while GPUs 0 and 2 host halves of a tp=2 model. The
        new lane must land on GPU 1, not get packed next to gpt-oss."""
        lanes = [
            _lane(lane_id="big", model_name="openai/gpt-oss-120b", gpu_devices="0,2", effective_vram_mb=96_900.0),
        ]
        planner = _planner({0: 46_000.0, 1: 95_000.0, 2: 46_000.0}, lanes)

        placement = planner._pick_cold_load_placement(  # noqa: SLF001
            1,
            21_500.0,
            1,
            lanes,
            {},
            target_model_name="org/embed-8b",
        )

        assert placement is not None
        gpu_set, eviction_set = placement
        assert gpu_set == frozenset({1})
        assert eviction_set == []

    def test_spanning_lane_weighs_more_than_single_gpu_lane(self):
        """Sharing with half of a 2-GPU lane is worse than sharing with a
        1-GPU lane: evicting the wide lane later frees memory on a GPU
        nobody asked about."""
        lanes = [
            _lane(lane_id="wide", model_name="m/wide", gpu_devices="0,2", effective_vram_mb=40_000.0),
            _lane(lane_id="narrow", model_name="m/narrow", gpu_devices="1", effective_vram_mb=40_000.0),
        ]
        planner = _planner({0: 50_000.0, 1: 50_000.0, 2: 50_000.0}, lanes)

        placement = planner._pick_cold_load_placement(  # noqa: SLF001
            1,
            20_000.0,
            1,
            lanes,
            {},
            target_model_name="org/new-model",
        )

        assert placement is not None
        gpu_set, _ = placement
        assert gpu_set == frozenset({1})

    def test_best_fit_within_same_crowding(self):
        """With no co-location anywhere, fall back to best-fit by free memory
        — the same tie-break the worker's auto-placement applies."""
        planner = _planner({0: 30_000.0, 1: 95_000.0}, [])

        placement = planner._pick_cold_load_placement(  # noqa: SLF001
            1,
            20_000.0,
            1,
            [],
            {},
            target_model_name="org/new-model",
        )

        assert placement is not None
        gpu_set, _ = placement
        assert gpu_set == frozenset({0})
