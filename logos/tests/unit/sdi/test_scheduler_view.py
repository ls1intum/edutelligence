"""Tests for get_model_scheduler_view, get_all_lane_signals, and get_model_profiles."""

from logos.queue import PriorityQueueManager
from logos.sdi.logosnode_facade import LogosNodeSchedulingDataFacade
from logos.sdi.models import LaneSchedulerSignals, ModelSchedulerView, ModelProfile


def _make_lane(
    lane_id="lane-1",
    model="llama3.3:latest",
    runtime_state="loaded",
    sleep_state="unsupported",
    vllm=False,
    active_requests=0,
    num_parallel=4,
    effective_vram_mb=8192.0,
    backend_metrics=None,
    loaded_models=None,
):
    lane = {
        "lane_id": lane_id,
        "model": model,
        "runtime_state": runtime_state,
        "sleep_state": sleep_state,
        "vllm": vllm,
        "active_requests": active_requests,
        "num_parallel": num_parallel,
        "effective_vram_mb": effective_vram_mb,
        "backend_metrics": backend_metrics or {},
        "loaded_models": loaded_models or [{"name": model}],
    }
    return lane


def _make_registry(lanes, devices=None, model_profiles=None):
    """Create a fake registry that returns the given lanes."""

    class _FakeRegistry:
        def __init__(self):
            self._snapshot = {
                "runtime": {
                    "lanes": lanes,
                    "devices": devices or {},
                    **({"model_profiles": model_profiles} if model_profiles else {}),
                }
            }

        def peek_runtime_snapshot(self, provider_id):  # noqa: ARG002
            return self._snapshot

        def peek_recent_samples(self, provider_id, *, after_snapshot_id=0):  # noqa: ARG002
            return []

    return _FakeRegistry()


def _build_facade(registry, model_id, model_name, monkeypatch, provider_id=12):
    queue_mgr = PriorityQueueManager()
    facade = LogosNodeSchedulingDataFacade(queue_mgr, runtime_registry=registry)

    monkeypatch.setattr(
        "logos.sdi.providers.logosnode_provider.LogosNodeDataProvider._load_provider_config",
        lambda self: {},
    )
    monkeypatch.setattr(
        "logos.sdi.providers.logosnode_provider.LogosNodeDataProvider._fetch_ps_data",
        lambda self: {"models": []},
    )

    facade.register_model(model_id, "logosnode", "http://fake", model_name, 65536, provider_id=provider_id)
    return facade


# ---------------------------------------------------------------------------
# ModelSchedulerView tests
# ---------------------------------------------------------------------------


def test_scheduler_view_loaded_vllm_and_sleeping_ollama(monkeypatch):
    """One loaded vLLM lane + one sleeping Ollama lane for same model
    → is_loaded=True, best_lane_state='loaded'."""
    lanes = [
        _make_lane(
            lane_id="vllm-1",
            model="llama3.3:latest",
            runtime_state="loaded",
            sleep_state="awake",
            vllm=True,
            active_requests=2,
            num_parallel=0,
            effective_vram_mb=12000.0,
            backend_metrics={
                "queue_waiting": 1.0,
                "requests_running": 2.0,
                "gpu_cache_usage_perc": 45.0,
                "ttft_histogram": {"0.1": 8, "0.5": 10, "+Inf": 10},
            },
        ),
        _make_lane(
            lane_id="ollama-1",
            model="llama3.3:latest",
            runtime_state="sleeping",
            sleep_state="sleeping",
            vllm=False,
            active_requests=0,
            num_parallel=4,
            effective_vram_mb=2000.0,
        ),
    ]
    registry = _make_registry(lanes)
    facade = _build_facade(registry, 101, "llama3.3:latest", monkeypatch)

    view = facade.get_model_scheduler_view(101, provider_id=12)
    assert view is not None
    assert view.is_loaded is True
    assert view.best_lane_state == "loaded"
    assert view.best_sleep_state == "awake"
    assert view.aggregate_active_requests == 2
    assert view.aggregate_queue_waiting == 1.0
    assert view.warmest_ttft_p95_seconds > 0
    assert view.gpu_cache_pressure_max == 45.0
    assert len(view.lanes) == 2

    # Verify lane signals
    vllm_lane = next(l for l in view.lanes if l.lane_id == "vllm-1")
    assert vllm_lane.is_vllm is True
    assert vllm_lane.requests_running == 2.0
    assert vllm_lane.gpu_cache_usage_percent == 45.0

    ollama_lane = next(l for l in view.lanes if l.lane_id == "ollama-1")
    assert ollama_lane.is_vllm is False
    assert ollama_lane.requests_running == 0.0  # Ollama uses active_requests for requests_running
    assert ollama_lane.gpu_cache_usage_percent is None


def test_scheduler_view_all_cold_lanes(monkeypatch):
    """All cold lanes → is_loaded=False, best_lane_state='cold'."""
    lanes = [
        _make_lane(lane_id="lane-1", runtime_state="cold", sleep_state="unsupported"),
        _make_lane(lane_id="lane-2", runtime_state="cold", sleep_state="unsupported"),
    ]
    registry = _make_registry(lanes)
    facade = _build_facade(registry, 101, "llama3.3:latest", monkeypatch)

    view = facade.get_model_scheduler_view(101, provider_id=12)
    assert view is not None
    assert view.is_loaded is False
    assert view.best_lane_state == "cold"
    assert view.best_sleep_state == "unsupported"
    assert view.warmest_ttft_p95_seconds == 0.0
    assert view.gpu_cache_pressure_max is None


def test_scheduler_view_vllm_with_backend_metrics(monkeypatch):
    """vLLM lane with rich backend_metrics → verify ttft_p95 and queue signals populated."""
    lanes = [
        _make_lane(
            lane_id="vllm-1",
            model="qwen3:8b",
            runtime_state="running",
            sleep_state="awake",
            vllm=True,
            active_requests=5,
            num_parallel=0,
            effective_vram_mb=10000.0,
            backend_metrics={
                "queue_waiting": 3.0,
                "requests_running": 5.0,
                "gpu_cache_usage_perc": 82.5,
                "ttft_histogram": {
                    "0.05": 50,
                    "0.1": 85,
                    "0.25": 95,
                    "0.5": 100,
                    "+Inf": 100,
                },
            },
        ),
    ]
    registry = _make_registry(lanes)
    facade = _build_facade(registry, 202, "qwen3:8b", monkeypatch)

    view = facade.get_model_scheduler_view(202, provider_id=12)
    assert view is not None
    assert view.is_loaded is True
    assert view.best_lane_state == "running"
    assert view.aggregate_queue_waiting == 3.0
    assert view.aggregate_active_requests == 5
    # p95 of 100 requests: 95th request at bucket 0.25
    assert view.warmest_ttft_p95_seconds == 0.25
    assert view.gpu_cache_pressure_max == 82.5


def test_scheduler_view_no_matching_lanes(monkeypatch):
    """No matching lanes for model → returns None."""
    lanes = [
        _make_lane(lane_id="lane-1", model="other-model:latest"),
    ]
    registry = _make_registry(lanes)
    facade = _build_facade(registry, 101, "llama3.3:latest", monkeypatch)

    view = facade.get_model_scheduler_view(101, provider_id=12)
    assert view is None


def test_scheduler_view_no_runtime_registry(monkeypatch):
    """Provider without runtime registry → returns None."""
    queue_mgr = PriorityQueueManager()
    facade = LogosNodeSchedulingDataFacade(queue_mgr, runtime_registry=None)

    monkeypatch.setattr(
        "logos.sdi.providers.logosnode_provider.LogosNodeDataProvider._load_provider_config",
        lambda self: {},
    )
    monkeypatch.setattr(
        "logos.sdi.providers.logosnode_provider.LogosNodeDataProvider._fetch_ps_data",
        lambda self: {"models": []},
    )

    facade.register_model(101, "logosnode", "http://fake", "llama3.3:latest", 65536, provider_id=12)
    view = facade.get_model_scheduler_view(101, provider_id=12)
    assert view is None


def test_scheduler_view_includes_stopped_error_lanes(monkeypatch):
    """Stopped/error lanes are included in signals for planner visibility."""
    lanes = [
        _make_lane(lane_id="lane-1", runtime_state="running", sleep_state="awake"),
        _make_lane(lane_id="lane-2", runtime_state="stopped", sleep_state="unsupported"),
        _make_lane(lane_id="lane-3", runtime_state="error", sleep_state="unsupported"),
    ]
    registry = _make_registry(lanes)
    facade = _build_facade(registry, 101, "llama3.3:latest", monkeypatch)

    view = facade.get_model_scheduler_view(101, provider_id=12)
    assert view is not None
    assert len(view.lanes) == 3
    assert view.best_lane_state == "running"  # running is warmest
    assert view.is_loaded is True


def test_scheduler_view_to_dict_roundtrip(monkeypatch):
    """Verify to_dict produces valid serializable output."""
    lanes = [
        _make_lane(
            lane_id="vllm-1",
            runtime_state="loaded",
            sleep_state="awake",
            vllm=True,
            backend_metrics={"queue_waiting": 2.0, "requests_running": 1.0},
        ),
    ]
    registry = _make_registry(lanes)
    facade = _build_facade(registry, 101, "llama3.3:latest", monkeypatch)

    view = facade.get_model_scheduler_view(101, provider_id=12)
    d = view.to_dict()
    assert d["model_id"] == 101
    assert d["is_loaded"] is True
    assert isinstance(d["lanes"], list)
    assert len(d["lanes"]) == 1
    assert d["lanes"][0]["lane_id"] == "vllm-1"


# ---------------------------------------------------------------------------
# get_all_lane_signals tests
# ---------------------------------------------------------------------------


def test_get_all_lane_signals_returns_all_lanes(monkeypatch):
    """get_all_lane_signals returns signals for every lane regardless of model."""
    lanes = [
        _make_lane(lane_id="lane-1", model="model-a"),
        _make_lane(lane_id="lane-2", model="model-b"),
        _make_lane(lane_id="lane-3", model="model-c"),
    ]
    registry = _make_registry(lanes)
    facade = _build_facade(registry, 101, "model-a", monkeypatch)

    signals = facade.get_all_provider_lane_signals(provider_id=12)
    assert len(signals) == 3
    assert all(isinstance(s, LaneSchedulerSignals) for s in signals)
    signal_models = {s.model_name for s in signals}
    assert signal_models == {"model-a", "model-b", "model-c"}


def test_get_all_lane_signals_no_registry(monkeypatch):
    """No runtime registry → returns empty list."""
    queue_mgr = PriorityQueueManager()
    facade = LogosNodeSchedulingDataFacade(queue_mgr, runtime_registry=None)

    monkeypatch.setattr(
        "logos.sdi.providers.logosnode_provider.LogosNodeDataProvider._load_provider_config",
        lambda self: {},
    )
    monkeypatch.setattr(
        "logos.sdi.providers.logosnode_provider.LogosNodeDataProvider._fetch_ps_data",
        lambda self: {"models": []},
    )

    facade.register_model(101, "logosnode", "http://fake", "model-a", 65536, provider_id=12)
    signals = facade.get_all_provider_lane_signals(provider_id=12)
    assert signals == []


# ---------------------------------------------------------------------------
# get_model_profiles tests
# ---------------------------------------------------------------------------


def test_get_model_profiles_reads_from_snapshot(monkeypatch):
    """Model profiles are correctly read from runtime snapshot."""
    profiles_data = {
        "llama3.3:latest": {
            "loaded_vram_mb": 8192.0,
            "sleeping_residual_mb": 512.0,
            "disk_size_bytes": 4_000_000_000,
            "measurement_count": 5,
            "last_measured_epoch": 1710000000.0,
        },
        "qwen3:8b": {
            "loaded_vram_mb": 6000.0,
            "sleeping_residual_mb": None,
            "disk_size_bytes": None,
            "measurement_count": 1,
            "last_measured_epoch": 1710000100.0,
        },
    }
    registry = _make_registry(lanes=[], model_profiles=profiles_data)
    facade = _build_facade(registry, 101, "llama3.3:latest", monkeypatch)

    profiles = facade.get_model_profiles(provider_id=12)
    assert len(profiles) == 2

    llama = profiles["llama3.3:latest"]
    assert isinstance(llama, ModelProfile)
    assert llama.loaded_vram_mb == 8192.0
    assert llama.sleeping_residual_mb == 512.0
    assert llama.disk_size_bytes == 4_000_000_000
    assert llama.measurement_count == 5

    qwen = profiles["qwen3:8b"]
    assert qwen.loaded_vram_mb == 6000.0
    assert qwen.sleeping_residual_mb is None


def test_get_model_profiles_empty_when_no_profiles(monkeypatch):
    """No model_profiles in snapshot → returns empty dict."""
    registry = _make_registry(lanes=[])
    facade = _build_facade(registry, 101, "llama3.3:latest", monkeypatch)

    profiles = facade.get_model_profiles(provider_id=12)
    assert profiles == {}


def test_model_profile_estimate_vram_mb():
    """ModelProfile.estimate_vram_mb prefers measured > disk heuristic > fallback."""
    # Measured available
    p1 = ModelProfile(model_name="m1", loaded_vram_mb=8000.0)
    assert p1.estimate_vram_mb() == 8000.0

    # Only disk size available: disk_bytes / 1MB * 1.1
    p2 = ModelProfile(model_name="m2", disk_size_bytes=4 * 1024 * 1024 * 1024)
    expected = (4 * 1024 * 1024 * 1024 / (1024 * 1024)) * 1.1
    assert abs(p2.estimate_vram_mb() - expected) < 1.0

    # Nothing available: fallback 4096
    p3 = ModelProfile(model_name="m3")
    assert p3.estimate_vram_mb() == 4096.0


# ---------------------------------------------------------------------------
# provider_ids tests
# ---------------------------------------------------------------------------


def test_provider_ids(monkeypatch):
    """provider_ids returns all registered provider IDs."""
    lanes = [_make_lane()]
    registry = _make_registry(lanes)

    queue_mgr = PriorityQueueManager()
    facade = LogosNodeSchedulingDataFacade(queue_mgr, runtime_registry=registry)

    monkeypatch.setattr(
        "logos.sdi.providers.logosnode_provider.LogosNodeDataProvider._load_provider_config",
        lambda self: {},
    )
    monkeypatch.setattr(
        "logos.sdi.providers.logosnode_provider.LogosNodeDataProvider._fetch_ps_data",
        lambda self: {"models": []},
    )

    facade.register_model(101, "logosnode", "http://fake", "llama3.3:latest", 65536, provider_id=10)
    facade.register_model(102, "logosnode", "http://fake2", "qwen3:8b", 32768, provider_id=20)

    ids = facade.provider_ids()
    assert set(ids) == {10, 20}


# ---------------------------------------------------------------------------
# Warmth ordering static method tests
# ---------------------------------------------------------------------------


def test_warmest_state_ordering():
    """Verify warmth ordering: running > loaded > sleeping > starting > cold > stopped > error."""
    assert ModelSchedulerView.warmest_state(["cold", "loaded"]) == "loaded"
    assert ModelSchedulerView.warmest_state(["sleeping", "running"]) == "running"
    assert ModelSchedulerView.warmest_state(["error", "stopped"]) == "stopped"
    assert ModelSchedulerView.warmest_state(["starting", "cold"]) == "starting"
    assert ModelSchedulerView.warmest_state([]) == "error"
    # Unknown states get same index as error (beyond the end of warmth list)
    assert ModelSchedulerView.warmest_state(["unknown_state"]) == "error"


def test_warmest_sleep_ordering():
    """Verify sleep warmth: awake > unknown > sleeping > unsupported."""
    assert ModelSchedulerView.warmest_sleep(["sleeping", "awake"]) == "awake"
    assert ModelSchedulerView.warmest_sleep(["unsupported", "sleeping"]) == "sleeping"
    assert ModelSchedulerView.warmest_sleep(["unsupported", "unknown"]) == "unknown"
    assert ModelSchedulerView.warmest_sleep([]) == "unsupported"
