"""Tests for ModelProfileRegistry — observation-only, no estimation."""

import threading
import time

import pytest

from logos_worker_node.model_profiles import ModelProfileRecord, ModelProfileRegistry


def _round_trip(registry: ModelProfileRegistry, **kwargs) -> ModelProfileRegistry:
    """Restart the node: Logos stores the status echo and sends it back."""
    stored = {}
    for name, echoed in registry.get_all_profiles().items():
        skip = {"calibration_key_hash", "overridden_fields", *(echoed.get("overridden_fields") or [])}
        stored[name] = {k: v for k, v in echoed.items() if k not in skip}
    restarted = ModelProfileRegistry(**kwargs)
    restarted.replace_from_sync(stored)
    return restarted


def _registry_with(profiles: dict, **kwargs) -> ModelProfileRegistry:
    registry = ModelProfileRegistry(**kwargs)
    registry.replace_from_sync(profiles)
    return registry


# ---------------------------------------------------------------------------
# Basic record/retrieve
# ---------------------------------------------------------------------------


def _seed_disk_size(registry: ModelProfileRegistry, model_name: str, disk_size_bytes: int) -> None:
    """Inject the legacy disk_size_bytes field the way a stored profile carries it."""
    registry._profiles[model_name] = ModelProfileRecord(disk_size_bytes=disk_size_bytes)


def test_record_loaded_vram_with_kv_derives_base_residency():
    """When kv_cache_sent_mb is known, base_residency = loaded - kv_cache."""
    registry = ModelProfileRegistry()
    registry.record_loaded_vram(
        "org/model-7b",
        8000.0,
        engine="vllm",
        kv_cache_sent_mb=2048.0,
    )

    profile = registry.get_profile("org/model-7b")
    assert profile is not None
    assert profile.loaded_vram_mb == 8000.0
    assert profile.base_residency_mb == pytest.approx(8000.0 - 2048.0)
    assert profile.kv_budget_mb == pytest.approx(2048.0)
    assert profile.residency_source == "measured"
    assert profile.measurement_count == 1


def test_record_loaded_vram_without_kv_leaves_base_residency_none():
    """Without kv_cache_sent_mb, base_residency_mb is not touched — no guessing."""
    registry = ModelProfileRegistry()
    registry.record_loaded_vram("llama3:8b", 8000.0, engine="vllm")

    profile = registry.get_profile("llama3:8b")
    assert profile is not None
    assert profile.loaded_vram_mb == 8000.0
    assert profile.base_residency_mb is None
    assert profile.kv_budget_mb is None


def test_record_loaded_vram_without_kv_updates_loaded_vram_only():
    """Without a kv budget, only loaded_vram_mb is tracked."""
    registry = ModelProfileRegistry()
    registry.record_loaded_vram("gemma-2b", 3000.0, engine="vllm")

    profile = registry.get_profile("gemma-2b")
    assert profile.loaded_vram_mb == 3000.0
    assert profile.base_residency_mb is None


def test_record_successful_load_util_tracks_lowest_known_good_value():
    registry = ModelProfileRegistry()
    registry.record_successful_load_util("qwen-coder", 0.8)
    registry.record_successful_load_util("qwen-coder", 0.7)
    registry.record_successful_load_util("qwen-coder", 0.75)

    profile = registry.get_profile("qwen-coder")
    assert profile is not None
    assert profile.min_gpu_memory_utilization_to_load == 0.7


def test_record_loaded_vram_subsequent_uses_ema():
    registry = ModelProfileRegistry()
    registry.record_loaded_vram("llama3:8b", 8000.0, engine="vllm", kv_cache_sent_mb=2000.0)
    registry.record_loaded_vram("llama3:8b", 9000.0, engine="vllm", kv_cache_sent_mb=2000.0)

    profile = registry.get_profile("llama3:8b")
    assert profile is not None
    # EMA loaded: 0.3 * 9000 + 0.7 * 8000 = 8300
    assert abs(profile.loaded_vram_mb - 8300.0) < 1.0
    # EMA base: first=6000, second EMA(6000, 7000)=6300
    assert abs(profile.base_residency_mb - 6300.0) < 1.0
    assert profile.measurement_count == 2


def test_record_loaded_vram_after_hf_precheck_uses_measurement_exactly():
    """residency_source="hf" is a best-effort guess, not a prior real
    measurement — the first live load must replace it exactly, not blend
    through _ema() and keep 70% weight on a guess that could be badly off."""
    registry = ModelProfileRegistry()
    registry.apply_hf_precheck("org/model", disk_size_bytes=4_000_000_000, base_residency_mb=4200.0)
    profile = registry.get_profile("org/model")
    assert profile.residency_source == "hf"

    registry.record_loaded_vram("org/model", 9000.0, engine="vllm", kv_cache_sent_mb=2000.0)

    profile = registry.get_profile("org/model")
    assert profile.residency_source == "measured"
    assert profile.base_residency_mb == pytest.approx(9000.0 - 2000.0)


def test_record_loaded_vram_ignores_zero():
    registry = ModelProfileRegistry()
    registry.record_loaded_vram("llama3:8b", 0.0)

    profile = registry.get_profile("llama3:8b")
    assert profile is None


def test_record_sleeping_vram():
    registry = ModelProfileRegistry()
    registry.record_sleeping_vram("llama3:8b", 512.0)

    profile = registry.get_profile("llama3:8b")
    assert profile is not None
    assert profile.sleeping_residual_mb == 512.0


def test_record_sleeping_vram_ema():
    registry = ModelProfileRegistry()
    registry.record_sleeping_vram("llama3:8b", 500.0)
    registry.record_sleeping_vram("llama3:8b", 600.0)

    profile = registry.get_profile("llama3:8b")
    # EMA: 0.3 * 600 + 0.7 * 500 = 530
    assert abs(profile.sleeping_residual_mb - 530.0) < 1.0


def test_record_host_ram_keeps_high_water_mark_across_lean_replica():
    """Sticky EngineCore growth must not be averaged down by a fresh lean lane."""
    registry = ModelProfileRegistry()
    registry.record_host_ram("Qwen/Qwen3.8-27B", 80_000.0, sleeping=False)
    registry.record_host_ram("Qwen/Qwen3.8-27B", 5_500.0, sleeping=False)

    profile = registry.get_profile("Qwen/Qwen3.8-27B")
    assert profile is not None
    assert profile.host_ram_mb == 80_000.0


def test_record_host_ram_sleeping_keeps_high_water_mark():
    registry = ModelProfileRegistry()
    registry.record_host_ram("Qwen/Qwen3.8-27B", 70_000.0, sleeping=True)
    registry.record_host_ram("Qwen/Qwen3.8-27B", 8_000.0, sleeping=True)

    profile = registry.get_profile("Qwen/Qwen3.8-27B")
    assert profile is not None
    assert profile.host_ram_residual_mb == 70_000.0


def test_disk_size_bytes_does_not_derive_base_residency():
    """The legacy disk_size_bytes field is informational — no base_residency from it."""
    registry = ModelProfileRegistry()
    _seed_disk_size(registry, "llama3:8b", 4_000_000_000)

    profile = registry.get_profile("llama3:8b")
    assert profile is not None
    assert profile.disk_size_bytes == 4_000_000_000
    assert profile.base_residency_mb is None  # no estimation from disk size


# ---------------------------------------------------------------------------
# estimate_vram_mb — no estimation fallbacks
# ---------------------------------------------------------------------------


def test_estimate_vram_vllm_uses_base_residency():
    """vLLM engine: estimate_vram_mb returns base_residency_mb (not loaded_vram_mb)."""
    p = ModelProfileRecord(engine="vllm", base_residency_mb=5800.0, loaded_vram_mb=20000.0)
    assert p.estimate_vram_mb() == 5800.0


def test_estimate_vram_vllm_returns_zero_when_unknown():
    """vLLM with no base_residency returns 0.0 — caller must handle, no guessing."""
    p = ModelProfileRecord(engine="vllm")
    assert p.estimate_vram_mb() == 0.0


def test_estimate_vram_non_vllm_uses_loaded_vram():
    """Non-vLLM: estimate_vram_mb returns loaded_vram_mb."""
    p = ModelProfileRecord(loaded_vram_mb=8000.0)
    assert p.estimate_vram_mb() == 8000.0


def test_estimate_vram_fallback_zero_when_nothing_known():
    """No data at all → returns 0.0 (no speculative fallback)."""
    p = ModelProfileRecord()
    assert p.estimate_vram_mb() == 0.0


def test_estimate_base_residency_returns_stored_value():
    """estimate_base_residency_mb returns base_residency_mb; no name/disk fallback."""
    p = ModelProfileRecord(base_residency_mb=6000.0)
    assert p.estimate_base_residency_mb("org/model-7b") == 6000.0


def test_estimate_base_residency_returns_none_when_unknown():
    p = ModelProfileRecord()
    assert p.estimate_base_residency_mb("org/model-7b") is None


# ---------------------------------------------------------------------------
# get_all_profiles serialization
# ---------------------------------------------------------------------------


def test_get_all_profiles():
    registry = ModelProfileRegistry()
    registry.record_loaded_vram("llama3:8b", 8000.0)
    _seed_disk_size(registry, "qwen3:8b", 5_000_000_000)

    profiles = registry.get_all_profiles()
    assert len(profiles) == 2
    assert "llama3:8b" in profiles
    assert "qwen3:8b" in profiles
    assert profiles["llama3:8b"]["loaded_vram_mb"] == 8000.0
    assert profiles["qwen3:8b"]["disk_size_bytes"] == 5_000_000_000


# ---------------------------------------------------------------------------
# Round trip through Logos (the node keeps no profile file)
# ---------------------------------------------------------------------------


def test_persist_and_reload():
    """Write to temp state dir, create new registry from same dir, verify loaded."""
    registry1 = ModelProfileRegistry()
    registry1.record_loaded_vram(
        "llama3:8b",
        8000.0,
        engine="vllm",
        observed_gpu_memory_utilization=0.75,
        tensor_parallel_size=2,
        kv_cache_sent_mb=2048.0,
    )
    registry1.record_successful_load_util("llama3:8b", 0.72)
    registry1.record_sleeping_vram("llama3:8b", 512.0)
    _seed_disk_size(registry1, "qwen3:8b", 5_000_000_000)

    registry2 = _round_trip(registry1)
    profiles = registry2.get_all_profiles()
    assert len(profiles) == 2

    llama = registry2.get_profile("llama3:8b")
    assert llama is not None
    assert llama.loaded_vram_mb == 8000.0
    assert llama.base_residency_mb == pytest.approx(8000.0 - 2048.0)
    assert llama.sleeping_residual_mb == 512.0
    assert llama.engine == "vllm"
    assert llama.observed_gpu_memory_utilization == 0.75
    assert llama.min_gpu_memory_utilization_to_load == 0.72
    assert llama.tensor_parallel_size == 2
    assert llama.residency_source == "measured"

    qwen = registry2.get_profile("qwen3:8b")
    assert qwen is not None
    assert qwen.disk_size_bytes == 5_000_000_000
    assert qwen.base_residency_mb is None  # disk size does not derive base_residency


def test_calibrated_profile_survives_restart():
    """Calibrated profiles sent by Logos are loaded and trusted on restart."""

    # A calibrated profile as Logos sends it
    calibrated_data = {
        "model_profiles": {
            "Qwen/Qwen2.5-Coder-7B-Instruct-AWQ": {
                "loaded_vram_mb": 7296.0,
                "sleeping_residual_mb": 4800.0,
                "disk_size_bytes": None,
                "base_residency_mb": 5248.0,
                "kv_budget_mb": None,
                "engine": "vllm",
                "tensor_parallel_size": 1,
                "residency_source": "calibrated",
                "measurement_count": 1,
                "last_measured_epoch": time.time(),
                "observed_gpu_memory_utilization": None,
                "min_gpu_memory_utilization_to_load": None,
                "kv_per_token_bytes": None,
                "max_context_length": None,
            }
        }
    }

    registry = _registry_with(calibrated_data["model_profiles"])
    profile = registry.get_profile("Qwen/Qwen2.5-Coder-7B-Instruct-AWQ")

    assert profile is not None
    assert profile.base_residency_mb == pytest.approx(5248.0)
    assert profile.sleeping_residual_mb == pytest.approx(4800.0)
    assert profile.loaded_vram_mb == pytest.approx(7296.0)
    assert profile.residency_source == "calibrated"
    assert profile.engine == "vllm"


def test_calibrated_profile_not_overwritten_by_subsequent_load():
    """After calibration, first real load updates via EMA but source becomes 'measured'."""

    calibrated_data = {
        "model_profiles": {
            "org/model": {
                "loaded_vram_mb": 7000.0,
                "sleeping_residual_mb": 4500.0,
                "disk_size_bytes": None,
                "base_residency_mb": 5000.0,
                "kv_budget_mb": None,
                "engine": "vllm",
                "tensor_parallel_size": 1,
                "residency_source": "calibrated",
                "measurement_count": 1,
                "last_measured_epoch": time.time(),
                "observed_gpu_memory_utilization": None,
                "min_gpu_memory_utilization_to_load": None,
                "kv_per_token_bytes": None,
                "max_context_length": None,
            }
        }
    }

    registry = _registry_with(calibrated_data["model_profiles"])
    # Model actually loads — record the real measurement
    registry.record_loaded_vram("org/model", 7200.0, engine="vllm", kv_cache_sent_mb=2048.0)

    profile = registry.get_profile("org/model")
    # Calibrated base_residency is authoritative — it was measured on a clean
    # GPU and must not be EMA-blended with live measurements that can be
    # lower when multiple models share GPU memory. The runtime measurement
    # is still recorded against other fields (e.g. loaded_vram_mb) but the
    # provenance and value of base_residency_mb stay pinned.
    assert profile.base_residency_mb == 5000.0
    assert profile.residency_source == "calibrated"


def _calibrated_registry(tp: int) -> ModelProfileRegistry:
    """Registry holding a calibrated profile with TP-dependent KV data."""
    calibrated_data = {
        "model_profiles": {
            "org/model": {
                "loaded_vram_mb": 7000.0,
                "sleeping_residual_mb": 4500.0,
                "disk_size_bytes": None,
                "base_residency_mb": 5000.0,
                "kv_budget_mb": 2048.0,
                "engine": "vllm",
                "tensor_parallel_size": tp,
                "residency_source": "calibrated",
                "measurement_count": 1,
                "last_measured_epoch": time.time(),
                "observed_gpu_memory_utilization": None,
                "min_gpu_memory_utilization_to_load": None,
                "kv_per_token_bytes": None,
                "max_context_length": None,
                "kv_cache_to_max_model_len_pairs": [{"kv_mb": 2048.0, "max_model_len": 5232}],
            }
        }
    }
    return _registry_with(calibrated_data["model_profiles"])


def test_calibrated_tp_not_clobbered_by_mismatched_lane():
    """A serving lane that ran at a TP different from the calibrated TP must
    not overwrite the profile: the calibrated TP is the single
    source of truth, and the lane's measurements describe a different
    configuration. The whole profile — tp, residency, KV data — stays intact.
    """
    registry = _calibrated_registry(tp=1)
    registry.record_loaded_vram(
        "org/model",
        9000.0,
        engine="vllm",
        tensor_parallel_size=2,
        kv_cache_sent_mb=2048.0,
    )

    profile = registry.get_profile("org/model")
    assert profile.tensor_parallel_size == 1
    assert profile.base_residency_mb == 5000.0
    assert profile.residency_source == "calibrated"
    assert profile.loaded_vram_mb == 7000.0  # untouched, not EMA-blended
    assert profile.kv_cache_to_max_model_len_pairs == [{"kv_mb": 2048.0, "max_model_len": 5232}]
    assert profile.measurement_count == 1  # the mismatched measurement was discarded


def test_calibrated_tp_not_clobbered_by_mismatched_sleep():
    """Same guard on the sleep path: a mismatched-TP residual records nothing."""
    registry = _calibrated_registry(tp=1)
    registry.record_sleeping_vram("org/model", 300.0, engine="vllm", tensor_parallel_size=2)

    profile = registry.get_profile("org/model")
    assert profile.tensor_parallel_size == 1
    assert profile.sleeping_residual_mb == 4500.0  # untouched
    assert profile.residency_source == "calibrated"


def test_calibrated_profile_matching_tp_records_measurements():
    """A lane that runs at the calibrated TP records as usual — the guard only
    fires on a TP mismatch."""
    registry = _calibrated_registry(tp=1)
    registry.record_loaded_vram("org/model", 7200.0, engine="vllm", tensor_parallel_size=1, kv_cache_sent_mb=2048.0)

    profile = registry.get_profile("org/model")
    assert profile.tensor_parallel_size == 1
    # EMA-blended with the calibrated 7000: 0.3 * 7200 + 0.7 * 7000 = 7060
    assert profile.loaded_vram_mb == pytest.approx(7060.0)
    assert profile.base_residency_mb == 5000.0  # calibrated value stays pinned
    assert profile.residency_source == "calibrated"
    assert profile.measurement_count == 2


# ---------------------------------------------------------------------------
# seed_capabilities
# ---------------------------------------------------------------------------


def test_seed_capabilities_creates_stub_profile():
    """seed_capabilities creates a minimal profile with engine set."""
    registry = ModelProfileRegistry()
    registry.seed_capabilities(["org/new-model"])

    profile = registry.get_profile("org/new-model")
    assert profile is not None
    assert profile.engine == "vllm"
    assert profile.base_residency_mb is None  # no calibration data yet


def test_seed_capabilities_skips_existing_calibrated_profile():
    """seed_capabilities does not overwrite a calibrated profile restored from Logos."""

    calibrated_data = {
        "model_profiles": {
            "org/model": {
                "base_residency_mb": 5000.0,
                "sleeping_residual_mb": 4000.0,
                "loaded_vram_mb": 7000.0,
                "engine": "vllm",
                "residency_source": "calibrated",
                "measurement_count": 1,
                "last_measured_epoch": time.time(),
                "disk_size_bytes": None,
                "kv_budget_mb": None,
                "observed_gpu_memory_utilization": None,
                "min_gpu_memory_utilization_to_load": None,
                "tensor_parallel_size": 1,
                "kv_per_token_bytes": None,
                "max_context_length": None,
            }
        }
    }

    registry = _registry_with(calibrated_data["model_profiles"])
    registry.seed_capabilities(["org/model"])

    profile = registry.get_profile("org/model")
    assert profile.base_residency_mb == pytest.approx(5000.0)
    assert profile.residency_source == "calibrated"


def test_seed_capabilities_sets_engine_if_missing():
    """seed_capabilities sets engine on existing profile if it was None."""
    registry = ModelProfileRegistry()
    registry._profiles["model/b"] = ModelProfileRecord(loaded_vram_mb=3000.0)
    registry.seed_capabilities(["model/b"], engine="vllm")

    profile = registry.get_profile("model/b")
    assert profile.engine == "vllm"
    assert profile.loaded_vram_mb == 3000.0  # preserved


def test_seed_capabilities_applies_manual_overrides():
    """Manual overrides from config.yml are applied to newly seeded profiles."""
    registry = ModelProfileRegistry(
        model_profile_overrides={
            "org/model": {"base_residency_mb": 6000.0, "tensor_parallel_size": 2},
        }
    )
    registry.seed_capabilities(["org/model"])

    profile = registry.get_profile("org/model")
    assert profile.base_residency_mb == pytest.approx(6000.0)
    assert profile.tensor_parallel_size == 2
    assert profile.residency_source == "override"


# ---------------------------------------------------------------------------
# Manual overrides
# ---------------------------------------------------------------------------


def test_manual_override_base_residency():
    registry = ModelProfileRegistry(
        model_profile_overrides={
            "org/model": {"base_residency_mb": 7500.0},
        }
    )
    registry.seed_capabilities(["org/model"])

    profile = registry.get_profile("org/model")
    assert profile.base_residency_mb == pytest.approx(7500.0)
    assert profile.residency_source == "override"


# ---------------------------------------------------------------------------
# HF compatibility precheck
# ---------------------------------------------------------------------------


def test_apply_hf_precheck_sets_fields_on_fresh_profile():
    registry = ModelProfileRegistry()
    changed = registry.apply_hf_precheck(
        "org/model",
        disk_size_bytes=4_000_000_000,
        base_residency_mb=4200.0,
        kv_per_token_bytes=1024,
        max_context_length=8192,
    )

    assert changed is True
    profile = registry.get_profile("org/model")
    assert profile.disk_size_bytes == 4_000_000_000
    assert profile.base_residency_mb == pytest.approx(4200.0)
    assert profile.kv_per_token_bytes == 1024
    assert profile.max_context_length == 8192
    assert profile.residency_source == "hf"


def test_apply_hf_precheck_does_not_downgrade_a_real_measurement():
    """A calibrated/measured base_residency_mb must survive an HF precheck
    run afterward (e.g. a later session re-checking an already-calibrated
    model) — only kv_per_token_bytes/max_context_length/disk_size_bytes,
    which calibration never measures, should still update."""
    registry = ModelProfileRegistry()
    registry.record_loaded_vram("org/model", 9000.0, engine="vllm", kv_cache_sent_mb=2000.0)
    profile = registry.get_profile("org/model")
    assert profile.residency_source == "measured"

    changed = registry.apply_hf_precheck(
        "org/model",
        disk_size_bytes=4_000_000_000,
        base_residency_mb=1234.0,
        kv_per_token_bytes=1024,
        max_context_length=8192,
    )

    assert changed is True
    profile = registry.get_profile("org/model")
    assert profile.residency_source == "measured"
    assert profile.base_residency_mb == pytest.approx(9000.0 - 2000.0)
    assert profile.disk_size_bytes == 4_000_000_000
    assert profile.kv_per_token_bytes == 1024
    assert profile.max_context_length == 8192


def test_apply_hf_precheck_respects_manual_override():
    registry = ModelProfileRegistry(
        model_profile_overrides={
            "org/model": {"base_residency_mb": 7500.0},
        }
    )
    registry.seed_capabilities(["org/model"])

    registry.apply_hf_precheck("org/model", base_residency_mb=1234.0, kv_per_token_bytes=1024)

    profile = registry.get_profile("org/model")
    assert profile.base_residency_mb == pytest.approx(7500.0)
    assert profile.residency_source == "override"
    # kv_per_token_bytes has no override, so the HF value still lands.
    assert profile.kv_per_token_bytes == 1024


def test_apply_hf_precheck_does_not_overwrite_an_override_added_mid_call():
    """Regression: the manual-overrides lookup must happen inside the
    same lock add_overrides uses. Simulates the model's first override
    landing in the window between an unlocked lookup and the lock —
    whichever order the two calls serialize in, the override must win."""
    registry = ModelProfileRegistry()
    registry.seed_capabilities(["org/model"])
    override_applied = threading.Event()

    def _add_override_from_another_thread():
        registry.add_overrides({"org/model": {"kv_per_token_bytes": 999}})
        override_applied.set()

    class _RacyOverrides(dict):
        def get(self, key, default=None):
            stale = dict.get(self, key, default)
            if key == "org/model" and "org/model" not in self:
                threading.Thread(target=_add_override_from_another_thread).start()
                override_applied.wait(timeout=0.2)
            return stale

    registry._manual_overrides = _RacyOverrides(registry._manual_overrides)  # noqa: SLF001

    registry.apply_hf_precheck("org/model", kv_per_token_bytes=1024)
    override_applied.wait(timeout=1.0)

    profile = registry.get_profile("org/model")
    assert profile.kv_per_token_bytes == 999


def test_apply_hf_precheck_persists_across_restart():
    registry = ModelProfileRegistry()
    registry.apply_hf_precheck(
        "org/model",
        disk_size_bytes=4_000_000_000,
        base_residency_mb=4200.0,
        kv_per_token_bytes=1024,
        max_context_length=8192,
    )

    reloaded = _round_trip(registry)
    profile = reloaded.get_profile("org/model")
    assert profile is not None
    assert profile.base_residency_mb == pytest.approx(4200.0)
    assert profile.kv_per_token_bytes == 1024
    assert profile.max_context_length == 8192
    assert profile.residency_source == "hf"


def test_kv_per_token_in_to_dict():
    """kv_per_token_bytes and max_context_length are included in serialization."""
    record = ModelProfileRecord(kv_per_token_bytes=57344, max_context_length=32768)
    d = record.to_dict()
    assert d["kv_per_token_bytes"] == 57344
    assert d["max_context_length"] == 32768


# ---------------------------------------------------------------------------
# Thread safety (basic)
# ---------------------------------------------------------------------------


def test_concurrent_record():
    """Basic thread safety — no crash under concurrent writes."""
    import concurrent.futures

    registry = ModelProfileRegistry()

    def record_batch(model_name, count):
        for i in range(count):
            registry.record_loaded_vram(model_name, 5000.0 + i)

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(record_batch, f"model-{n}", 50) for n in range(4)]
        for f in futures:
            f.result()

    profiles = registry.get_all_profiles()
    assert len(profiles) == 4
    for name in ["model-0", "model-1", "model-2", "model-3"]:
        assert name in profiles
        assert profiles[name]["measurement_count"] == 50


# ---------------------------------------------------------------------------
# KV cache envelope (min_kv_cache_mb / max_kv_cache_mb)
# ---------------------------------------------------------------------------


def test_kv_envelope_to_dict_round_trip():
    """min/max_kv_cache_mb appear in to_dict() so they survive YAML and heartbeats."""
    p = ModelProfileRecord(min_kv_cache_mb=1024.0, max_kv_cache_mb=30720.0)
    data = p.to_dict()
    assert data["min_kv_cache_mb"] == 1024.0
    assert data["max_kv_cache_mb"] == 30720.0


def test_kv_envelope_defaults_to_none():
    """Legacy profiles written before the envelope existed keep both fields None."""
    p = ModelProfileRecord()
    assert p.min_kv_cache_mb is None
    assert p.max_kv_cache_mb is None
    data = p.to_dict()
    assert data["min_kv_cache_mb"] is None
    assert data["max_kv_cache_mb"] is None


def test_kv_envelope_persists_across_restart():
    """The round trip through Logos preserves both endpoints of the envelope."""
    registry1 = ModelProfileRegistry()
    registry1.record_loaded_vram(
        "envelope/model",
        20000.0,
        engine="vllm",
        kv_cache_sent_mb=4096.0,
    )
    # Simulate calibration writing the envelope by mutating the loaded
    # profile directly — record_loaded_vram itself does not yet set min/max
    # because the worker writes those via the calibration result dict path.
    profile = registry1.get_profile("envelope/model")
    assert profile is not None
    profile.min_kv_cache_mb = 1024.0
    profile.max_kv_cache_mb = 30720.0

    registry2 = _round_trip(registry1)
    reloaded = registry2.get_profile("envelope/model")
    assert reloaded is not None
    assert reloaded.min_kv_cache_mb == 1024.0
    assert reloaded.max_kv_cache_mb == 30720.0


def test_kv_envelope_manual_override_applies():
    """Operator-pinned min/max in config.yml flow through ``model_profile_overrides``."""
    registry = ModelProfileRegistry(
        model_profile_overrides={
            "operator/pinned": {
                "min_kv_cache_mb": 2048.0,
                "max_kv_cache_mb": 8192.0,
            }
        }
    )
    registry.seed_capabilities(["operator/pinned"], engine="vllm")
    profile = registry.get_profile("operator/pinned")
    assert profile is not None
    assert profile.min_kv_cache_mb == 2048.0
    assert profile.max_kv_cache_mb == 8192.0


def test_kv_pairs_override_preserves_parallelity():
    """The parallelity factor on each kv pair survives the override merge."""
    registry = ModelProfileRegistry(
        model_profile_overrides={
            "operator/pinned": {
                "kv_cache_to_max_model_len_pairs": [
                    {"kv_mb": 1024.0, "max_model_len": 33888, "parallelity": 2.0},
                    {"kv_mb": 2048.0, "max_model_len": 33888, "parallelity": 4.0},
                    {"kv_mb": 512.0, "max_model_len": 16944},  # legacy entry, no parallelity
                ]
            }
        }
    )
    registry.seed_capabilities(["operator/pinned"], engine="vllm")
    profile = registry.get_profile("operator/pinned")
    assert profile is not None
    pairs = profile.kv_cache_to_max_model_len_pairs
    assert pairs is not None
    by_kv = {p["kv_mb"]: p for p in pairs}
    assert by_kv[1024.0]["parallelity"] == 2.0
    assert by_kv[2048.0]["parallelity"] == 4.0
    assert "parallelity" not in by_kv[512.0]


def test_calibration_max_model_len_to_dict_round_trip():
    """The auto-shrunk --max-model-len appears in to_dict() so the status
    echo, and with it Logos' copy, preserves it.

    Regression: without this field on ModelProfileRecord, calibration's
    successfully-shrunk value got dropped on the first re-store, and the
    lane spawner silently fell back to vLLM's default max_seq_len.
    """
    p = ModelProfileRecord(calibration_max_model_len=115632)
    assert p.to_dict()["calibration_max_model_len"] == 115632


def test_calibration_max_model_len_defaults_to_none():
    """Legacy profiles without the field stay None through to_dict()."""
    p = ModelProfileRecord()
    assert p.calibration_max_model_len is None
    assert p.to_dict()["calibration_max_model_len"] is None


def test_calibration_max_model_len_persists_across_restart():
    """The round trip through Logos preserves the auto-shrunk value across worker restarts."""
    registry1 = ModelProfileRegistry()
    registry1.record_loaded_vram(
        "shrunk/model",
        20000.0,
        engine="vllm",
        kv_cache_sent_mb=8192.0,
    )
    # Calibration writes the shrunk value via result_to_profile_dict; mirror
    # that here by mutating the loaded profile directly so the test exercises
    # the record → store → restore chain that was dropping the field.
    profile = registry1.get_profile("shrunk/model")
    assert profile is not None
    profile.calibration_max_model_len = 115632

    registry2 = _round_trip(registry1)
    reloaded = registry2.get_profile("shrunk/model")
    assert reloaded is not None
    assert reloaded.calibration_max_model_len == 115632


def test_calibration_max_model_len_manual_override_applies():
    """Operator-pinned ``calibration_max_model_len`` from config.yml flows through.

    Backfill knob for profiles already written before the field was plumbed
    end-to-end: ops can set it in ``model_profile_overrides`` without waiting
    for a recalibration window.
    """
    registry = ModelProfileRegistry(model_profile_overrides={"operator/pinned": {"calibration_max_model_len": 98304}})
    registry.seed_capabilities(["operator/pinned"], engine="vllm")
    profile = registry.get_profile("operator/pinned")
    assert profile is not None
    assert profile.calibration_max_model_len == 98304


def test_calibration_max_num_seqs_to_dict_round_trip():
    p = ModelProfileRecord(calibration_max_num_seqs=160)
    assert p.to_dict()["calibration_max_num_seqs"] == 160


def test_calibration_max_num_seqs_defaults_to_none():
    p = ModelProfileRecord()
    assert p.calibration_max_num_seqs is None
    assert p.to_dict()["calibration_max_num_seqs"] is None


def test_calibration_max_num_seqs_persists_across_restart():
    """The round trip through Logos preserves the auto-detected Mamba cap across restarts."""
    registry1 = ModelProfileRegistry()
    registry1.record_loaded_vram("mamba/model", 20000.0, engine="vllm", kv_cache_sent_mb=8192.0)
    profile = registry1.get_profile("mamba/model")
    assert profile is not None
    profile.calibration_max_num_seqs = 160

    registry2 = _round_trip(registry1)
    reloaded = registry2.get_profile("mamba/model")
    assert reloaded is not None
    assert reloaded.calibration_max_num_seqs == 160


def test_calibration_max_num_seqs_manual_override_applies():
    """Operator-pinned ``calibration_max_num_seqs`` from config.yml flows through."""
    registry = ModelProfileRegistry(model_profile_overrides={"operator/pinned": {"calibration_max_num_seqs": 160}})
    registry.seed_capabilities(["operator/pinned"], engine="vllm")
    profile = registry.get_profile("operator/pinned")
    assert profile is not None
    assert profile.calibration_max_num_seqs == 160


def test_kv_max_model_len_pairs_to_dict_round_trip():
    p = ModelProfileRecord(
        kv_cache_to_max_model_len_pairs=[
            {"kv_mb": 1024.0, "max_model_len": 1000},
            {"kv_mb": 2048.0, "max_model_len": 2000},
        ]
    )
    assert p.to_dict()["kv_cache_to_max_model_len_pairs"] == [
        {"kv_mb": 1024.0, "max_model_len": 1000},
        {"kv_mb": 2048.0, "max_model_len": 2000},
    ]


def test_kv_max_model_len_pairs_persist_across_restart():
    registry1 = ModelProfileRegistry()
    registry1.record_loaded_vram("pair/model", 20000.0, engine="vllm", kv_cache_sent_mb=8192.0)
    profile = registry1.get_profile("pair/model")
    assert profile is not None
    profile.kv_cache_to_max_model_len_pairs = [
        {"kv_mb": 1024.0, "max_model_len": 1000},
        {"kv_mb": 2048.0, "max_model_len": 2000},
    ]

    registry2 = _round_trip(registry1)
    reloaded = registry2.get_profile("pair/model")
    assert reloaded is not None
    assert reloaded.kv_cache_to_max_model_len_pairs == [
        {"kv_mb": 1024.0, "max_model_len": 1000},
        {"kv_mb": 2048.0, "max_model_len": 2000},
    ]


def test_add_overrides_reapplies_to_existing_record():
    """Overrides arriving after a record exists must reach the live record.

    Records restored from Logos are otherwise never revisited after startup,
    so a late override would stay in the config but not on the record — and
    the runtime snapshot the server planner reads would miss it.
    """
    registry = ModelProfileRegistry()
    registry.record_loaded_vram("org/model-27b", 50000.0, engine="vllm", kv_cache_sent_mb=8000.0)
    profile = registry.get_profile("org/model-27b")
    assert profile is not None
    assert profile.min_context_fraction is None

    registry.add_overrides({"org/model-27b": {"min_context_fraction": 0.5}})

    profile = registry.get_profile("org/model-27b")
    assert profile.min_context_fraction == 0.5


def test_add_overrides_before_record_creation_lands_on_seeded_record():
    """Overrides registered before the record exists apply at seed time."""
    registry = ModelProfileRegistry()
    registry.add_overrides({"org/model-7b": {"min_context_fraction": 1.0}})
    registry.seed_capabilities(["org/model-7b"], engine="vllm")

    profile = registry.get_profile("org/model-7b")
    assert profile is not None
    assert profile.min_context_fraction == 1.0


def test_calibrated_timing_fields_reload_and_serialize():
    """Cold-load / wake timings come back with the profile Logos sends."""

    calibrated_data = {
        "model_profiles": {
            "org/model": {
                "base_residency_mb": 5000.0,
                "engine": "vllm",
                "residency_source": "calibrated",
                "measurement_count": 1,
                "last_measured_epoch": time.time(),
                "cold_load_time_s": 91.5,
                "wake_from_sleep_time_s": 12.25,
            }
        }
    }

    registry = _registry_with(calibrated_data["model_profiles"])
    profile = registry.get_profile("org/model")
    assert profile is not None
    assert profile.cold_load_time_s == pytest.approx(91.5)
    assert profile.wake_from_sleep_time_s == pytest.approx(12.25)
    # The runtime snapshot the server planner reads must carry them too.
    dumped = registry.get_all_profiles()["org/model"]
    assert dumped["cold_load_time_s"] == pytest.approx(91.5)
    assert dumped["wake_from_sleep_time_s"] == pytest.approx(12.25)


def test_timing_fields_default_to_none_on_legacy_records():
    """Profiles written before the fields existed load with None, not 0.0."""
    registry = ModelProfileRegistry()
    registry.record_loaded_vram("org/model-7b", 8000.0, engine="vllm")

    profile = registry.get_profile("org/model-7b")
    assert profile is not None
    assert profile.cold_load_time_s is None
    assert profile.wake_from_sleep_time_s is None


@pytest.mark.parametrize("tp,cache,expected", [(2, 4096, 15988), (1, 4096, 11892), (2, 8192, 24180), (1, 0, 15988)])
def test_reconfigured_vram_replaces_only_known_per_rank_cache(tp, cache, expected):
    from logos_worker_node.model_profiles import reconfigured_vram_mb

    profile = ModelProfileRecord(residency_source="calibrated", tensor_parallel_size=2, kv_budget_mb=4096)
    assert reconfigured_vram_mb(profile, 15988, tp, cache) == expected
    profile.kv_budget_mb = None
    assert reconfigured_vram_mb(profile, 15988, tp, cache) == 15988


# ---------------------------------------------------------------------------
# mark_capacity_floor
# ---------------------------------------------------------------------------


def test_mark_capacity_floor_sets_value_on_fresh_profile():
    registry = ModelProfileRegistry()
    changed = registry.mark_capacity_floor("org/model", 16_000.0)

    assert changed is True
    profile = registry.get_profile("org/model")
    assert profile is not None
    assert profile.metal_capacity_floor_mb == pytest.approx(16_000.0)


def test_mark_capacity_floor_raises_but_never_lowers():
    """A bigger node failing too is stronger evidence; a smaller failed
    node reported after must not erase that stronger evidence."""
    registry = ModelProfileRegistry()
    registry.mark_capacity_floor("org/model", 16_000.0)

    raised = registry.mark_capacity_floor("org/model", 32_000.0)
    assert raised is True
    assert registry.get_profile("org/model").metal_capacity_floor_mb == pytest.approx(32_000.0)

    lowered = registry.mark_capacity_floor("org/model", 8_000.0)
    assert lowered is False
    assert registry.get_profile("org/model").metal_capacity_floor_mb == pytest.approx(32_000.0)


def test_mark_capacity_floor_round_trips_in_to_dict():
    registry = ModelProfileRegistry()
    registry.mark_capacity_floor("org/model", 24_000.0)

    dumped = registry.get_all_profiles()["org/model"]
    assert dumped["metal_capacity_floor_mb"] == pytest.approx(24_000.0)


def test_manual_override_clears_a_false_positive_capacity_floor():
    """An operator undoes a mistaken capacity-failure verdict by setting
    the override to null — the only way to lower/reset the stored value."""
    registry = ModelProfileRegistry()
    registry.mark_capacity_floor("org/model", 32_000.0)

    registry.add_overrides({"org/model": {"metal_capacity_floor_mb": None}})

    profile = registry.get_profile("org/model")
    assert profile.metal_capacity_floor_mb is None


def test_manual_override_pins_an_explicit_capacity_floor():
    registry = ModelProfileRegistry(
        model_profile_overrides={"org/model": {"metal_capacity_floor_mb": 12_000.0}},
    )
    registry.seed_capabilities(["org/model"])

    profile = registry.get_profile("org/model")
    assert profile.metal_capacity_floor_mb == pytest.approx(12_000.0)


# ---------------------------------------------------------------------------
# Sync with Logos
# ---------------------------------------------------------------------------


def test_sync_replaces_named_models_and_keeps_the_rest():
    registry = ModelProfileRegistry()
    registry.record_loaded_vram("org/kept", 8000.0, engine="vllm")
    replaced = registry.replace_from_sync({"org/new": {"base_residency_mb": 5.0, "sync_revision": 2}})
    assert replaced == ["org/new"]
    assert registry.get_profile("org/kept").loaded_vram_mb == 8000.0
    assert registry.get_profile("org/new").sync_revision == 2


def test_sync_reapplies_config_overrides_on_top():
    registry = ModelProfileRegistry(model_profile_overrides={"org/m": {"max_context_length": 32768}})
    registry.replace_from_sync({"org/m": {"max_context_length": 4096, "sync_revision": 1}})
    assert registry.get_profile("org/m").max_context_length == 32768
    assert registry.get_all_profiles()["org/m"]["overridden_fields"] == ["max_context_length"]


def test_overrides_never_reach_the_stored_copy():
    """Logos stores the echo without overridden fields; dropping the override
    from config.yml then leaves no stale value behind."""
    pinned = ModelProfileRegistry(model_profile_overrides={"org/m": {"max_context_length": 32768}})
    pinned.replace_from_sync({"org/m": {"base_residency_mb": 5.0, "sync_revision": 1}})
    assert _round_trip(pinned).get_profile("org/m").max_context_length is None


def test_a_local_calibration_waits_for_its_snapshot_id():
    registry = ModelProfileRegistry()
    registry.set_calibration_keys({"org/m": {"schema": 1, "plan_hash": "p"}})
    registry.replace_from_sync(
        {"org/m": {"base_residency_mb": 1.0, "host_ram_mb": 900.0, "sync_revision": 6, "calibration_id": 3}}
    )
    registry.apply_calibration_result("org/m", {"base_residency_mb": 15000.0, "residency_source": "calibrated"})

    echo = registry.get_all_profiles()["org/m"]
    assert echo["base_residency_mb"] == 15000.0
    assert echo["host_ram_mb"] == 900.0
    assert echo["calibration_origin"] == "local"
    assert echo["calibration_id"] is None
    assert echo["calibration_stale"] is False
    assert echo["calibration_key"] == {"schema": 1, "plan_hash": "p"}
    assert echo["sync_revision"] == 6


def test_sync_ignores_a_push_that_an_earlier_one_overtook():
    registry = ModelProfileRegistry()
    registry.replace_from_sync({"org/m": {"base_residency_mb": 9.0, "sync_revision": 5}})
    replaced = registry.replace_from_sync({"org/m": {"base_residency_mb": 1.0, "sync_revision": 4}})
    assert replaced == []
    assert registry.get_profile("org/m").base_residency_mb == 9.0


def test_sync_at_the_same_revision_keeps_measurements_and_refreshes_flags():
    """The push after every hello repeats the stored revision; it may only
    update what Logos derives, not what the node measured since."""
    registry = ModelProfileRegistry()
    registry.replace_from_sync({"org/m": {"engine": "vllm", "sync_revision": 3, "calibration_id": 7}})
    registry.record_loaded_vram("org/m", 8000.0, engine="vllm")
    registry.replace_from_sync({"org/m": {"sync_revision": 3, "calibration_id": 7, "calibration_stale": True}})
    profile = registry.get_profile("org/m")
    assert profile.loaded_vram_mb == 8000.0
    assert (profile.calibration_id, profile.calibration_stale) == (7, True)


def test_sync_at_the_same_revision_keeps_an_unlinked_local_calibration():
    registry = ModelProfileRegistry()
    registry.replace_from_sync({"org/m": {"base_residency_mb": 1.0, "sync_revision": 6}})
    registry.apply_calibration_result("org/m", {"base_residency_mb": 15000.0, "residency_source": "calibrated"})
    registry.replace_from_sync({"org/m": {"base_residency_mb": 1.0, "sync_revision": 6}})
    profile = registry.get_profile("org/m")
    assert (profile.base_residency_mb, profile.calibration_origin) == (15000.0, "local")


def test_sync_at_a_newer_revision_replaces_the_record():
    registry = ModelProfileRegistry()
    registry.replace_from_sync({"org/m": {"calibration_unsupported": True, "sync_revision": 2}})
    registry.replace_from_sync({"org/m": {"sync_revision": 3}})
    assert registry.get_profile("org/m").calibration_unsupported is None
