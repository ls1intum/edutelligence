"""model_profiles.yml is the only copy of every calibrated profile on a node.

Everything the planner needs to place a lane lives in that file, and for a
model that cannot sleep on its worker there is no second route back: a
skipped calibration leaves it without base_residency_mb, and a model without
base_residency_mb is never announced as a capability.

Observed in production: a nightly run reduced a node's store from 20 profiles
to 5, wiping the measurements of three models that had been serving for
months. The surviving five held nothing but the operator's config overrides —
the shape of freshly seeded capability stubs written over the real file.
"""

from __future__ import annotations

import pytest
import yaml

from logos_worker_node.calibration import (
    CalibrationResult,
    ProfileStoreUnreadableError,
    _build_vllm_cmd,
    load_existing_profiles,
    merge_profile,
    result_to_profile_dict,
    save_profiles,
)
from logos_worker_node.model_profiles import ModelProfileRegistry

# ---------------------------------------------------------------------------
# Reading: an unreadable store must not read as an empty one
# ---------------------------------------------------------------------------


def test_missing_store_reads_as_empty(tmp_path):
    assert load_existing_profiles(tmp_path / "model_profiles.yml") == {}


def test_store_without_a_profiles_section_reads_as_empty(tmp_path):
    path = tmp_path / "model_profiles.yml"
    path.write_text("other_key: 1\n")
    assert load_existing_profiles(path) == {}


def test_corrupt_store_raises_instead_of_returning_empty(tmp_path):
    """Callers write the returned dict back over the whole file, so an empty
    dict for an unreadable store deletes every profile in it."""
    path = tmp_path / "model_profiles.yml"
    path.write_text("model_profiles:\n  org/model: {unterminated\n")

    with pytest.raises(ProfileStoreUnreadableError):
        load_existing_profiles(path)


def test_truncated_store_raises(tmp_path):
    """What a reader could see mid-write before the save became atomic:
    open(path, "w") truncates first, so the window holds a partial file."""
    path = tmp_path / "model_profiles.yml"
    path.write_text('model_profiles:\n  org/model:\n    engine: "vll')

    with pytest.raises(ProfileStoreUnreadableError):
        load_existing_profiles(path)


def test_store_holding_a_non_mapping_raises(tmp_path):
    path = tmp_path / "model_profiles.yml"
    path.write_text("model_profiles:\n  - org/model\n")

    with pytest.raises(ProfileStoreUnreadableError):
        load_existing_profiles(path)


# ---------------------------------------------------------------------------
# Writing: atomic, and never a partial file
# ---------------------------------------------------------------------------


def test_save_profiles_round_trips(tmp_path):
    path = tmp_path / "model_profiles.yml"
    save_profiles(path, {"org/model": {"base_residency_mb": 98945.0}})

    assert load_existing_profiles(path) == {"org/model": {"base_residency_mb": 98945.0}}


def test_save_profiles_leaves_no_temp_file_behind(tmp_path):
    path = tmp_path / "model_profiles.yml"
    save_profiles(path, {"org/model": {"base_residency_mb": 1.0}})

    assert [p.name for p in tmp_path.iterdir()] == ["model_profiles.yml"]


def test_a_failed_save_leaves_the_previous_store_intact(tmp_path, monkeypatch):
    """The write goes to a temp file and is renamed, so a failure mid-dump
    cannot truncate the store that is already there."""
    path = tmp_path / "model_profiles.yml"
    save_profiles(path, {"org/model": {"base_residency_mb": 98945.0}})

    def _boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr("logos_worker_node.calibration.yaml.safe_dump", _boom)
    with pytest.raises(OSError, match="disk full"):
        save_profiles(path, {"org/other": {}})

    assert load_existing_profiles(path) == {"org/model": {"base_residency_mb": 98945.0}}


# ---------------------------------------------------------------------------
# Merging: a measurement updates a profile, it does not replace it
# ---------------------------------------------------------------------------


def test_merge_keeps_fields_the_probe_never_measures():
    """These are set elsewhere — by the sleep gate, the unsupported list, the
    host-RAM tracker — and assigning the result over the entry dropped them.
    A nosleep model losing sleep_mode_disabled is the worst case: the flag is
    what marks its null sleep fields as expected rather than as missing."""
    prior = {
        "base_residency_mb": 98945.0,
        "sleep_mode_disabled": True,
        "calibration_unsupported": False,
        "disk_size_bytes": 123456789,
        "host_ram_mb": 4096.0,
    }
    merged = merge_profile(prior, {"base_residency_mb": 99000.0, "disk_size_bytes": None})

    assert merged["base_residency_mb"] == 99000.0, "a measured value wins"
    assert merged["sleep_mode_disabled"] is True
    assert merged["calibration_unsupported"] is False
    assert merged["disk_size_bytes"] == 123456789, "None means not measured, not cleared"
    assert merged["host_ram_mb"] == 4096.0


def test_merge_writes_new_fields_including_nulls():
    merged = merge_profile({}, {"base_residency_mb": 1.0, "sleeping_residual_mb": None})

    assert merged == {"base_residency_mb": 1.0, "sleeping_residual_mb": None}


def test_merge_without_a_prior_entry():
    assert merge_profile(None, {"base_residency_mb": 1.0}) == {"base_residency_mb": 1.0}


def test_merge_does_not_mutate_the_prior_entry():
    prior = {"base_residency_mb": 1.0}
    merge_profile(prior, {"base_residency_mb": 2.0})
    assert prior == {"base_residency_mb": 1.0}


# ---------------------------------------------------------------------------
# The registry's own persistence
# ---------------------------------------------------------------------------


def test_registry_refuses_to_persist_over_a_store_it_could_not_read(tmp_path, caplog):
    """_persist rewrites the whole file from memory. After a failed load that
    memory is not a picture of the file — at startup it is a set of empty
    capability stubs carrying only config overrides, which is exactly what
    replaced 20 real profiles with 5 hollow ones in production."""
    path = tmp_path / "model_profiles.yml"
    path.write_text("model_profiles:\n  org/model: {unterminated\n")
    corrupt = path.read_text()

    registry = ModelProfileRegistry(
        state_dir=tmp_path,
        model_profile_overrides={"org/model": {"kv_budget_mb": 8192}},
    )
    assert registry._load_failed is True

    registry.seed_capabilities(["org/model"])

    assert path.read_text() == corrupt, "the unreadable store must be left alone"


def test_registry_persists_normally_once_the_store_reads(tmp_path):
    registry = ModelProfileRegistry(state_dir=tmp_path)
    assert registry._load_failed is False

    registry.record_loaded_vram("org/model", 8000.0, engine="vllm", kv_cache_sent_mb=2048.0)

    stored = yaml.safe_load((tmp_path / "model_profiles.yml").read_text())["model_profiles"]
    assert "org/model" in stored


def test_registry_reload_clears_the_failure_latch(tmp_path):
    """Repairing the file must re-enable persistence without a restart."""
    path = tmp_path / "model_profiles.yml"
    path.write_text("model_profiles:\n  org/model: {unterminated\n")
    registry = ModelProfileRegistry(state_dir=tmp_path)
    assert registry._load_failed is True

    save_profiles(path, {"org/model": {"base_residency_mb": 98945.0}})
    registry._load_persisted()

    assert registry._load_failed is False
    assert registry.get_profile("org/model").base_residency_mb == 98945.0


def test_registry_write_is_atomic(tmp_path):
    registry = ModelProfileRegistry(state_dir=tmp_path)
    registry.record_loaded_vram("org/model", 8000.0, engine="vllm", kv_cache_sent_mb=2048.0)

    assert sorted(p.name for p in tmp_path.iterdir()) == ["model_profiles.yml"]


# ---------------------------------------------------------------------------
# Calibrating a model that is not allowed to sleep
#
# Sleep is used by one of the six calibration phases, to measure
# sleeping_residual_mb. base_residency_mb — the value every placement decision
# reads — comes out of the awake measurement one phase earlier and does not
# depend on sleep at all. Refusing to calibrate without sleep left nosleep
# models permanently uncalibrated, and therefore permanently unavailable.
# ---------------------------------------------------------------------------


def _plan() -> dict:
    return {"model": "openai/gpt-oss-120b", "tensor_parallel_size": 2}


def test_probe_enables_sleep_mode_by_default():
    cmd = _build_vllm_cmd(_plan(), "vllm", "127.0.0.1", 18000, "8G")
    assert "--enable-sleep-mode" in cmd


def test_probe_omits_sleep_mode_for_a_nosleep_run():
    """Left on, vLLM swaps in CuMemAllocator and the probe measures a footprint
    production never runs — the serving lane has sleep off too."""
    plan = {**_plan(), "enable_sleep_mode": False}
    cmd = _build_vllm_cmd(plan, "vllm", "127.0.0.1", 18000, "8G")
    assert "--enable-sleep-mode" not in cmd


def test_a_result_without_a_sleep_measurement_persists_as_null():
    """Not 0.0 — that would read as "measured, and it releases everything"."""
    result = CalibrationResult(
        model="openai/gpt-oss-120b",
        tensor_parallel_size=2,
        gpu_devices="0,1",
        kv_cache_sent_mb=8192.0,
        success=True,
        base_residency_mb=98945.0,
        sleeping_residual_mb=None,
    )
    profile = result_to_profile_dict(result)

    assert profile["base_residency_mb"] == 98945.0
    assert profile["sleeping_residual_mb"] is None
    assert profile["residency_source"] == "calibrated"


def test_a_result_with_a_sleep_measurement_persists_it():
    result = CalibrationResult(
        model="org/model",
        tensor_parallel_size=1,
        gpu_devices="0",
        kv_cache_sent_mb=2048.0,
        success=True,
        base_residency_mb=12345.0,
        sleeping_residual_mb=512.44,
    )
    assert result_to_profile_dict(result)["sleeping_residual_mb"] == 512.4


def test_the_config_carries_enable_sleep_mode_into_the_plan(tmp_path):
    """This is what lets calibrate_model decide for itself, so the boot-time
    path (which asks for level 1 for everything) and the session-driven one
    agree without either knowing the other's rules."""
    from logos_worker_node.calibration import plans_from_config

    config = tmp_path / "config.yml"
    config.write_text(
        "logos:\n"
        "  capabilities_models:\n"
        "    - openai/gpt-oss-120b\n"
        "    - org/sleeper\n"
        "engines:\n"
        "  vllm:\n"
        "    model_overrides:\n"
        "      openai/gpt-oss-120b:\n"
        "        enable_sleep_mode: false\n"
        "        tensor_parallel_size: 2\n"
    )

    plans = {p["model"]: p for p in plans_from_config(config)}
    assert plans["openai/gpt-oss-120b"]["enable_sleep_mode"] is False
    assert "enable_sleep_mode" not in plans["org/sleeper"]


def test_a_plan_that_forbids_sleep_probes_at_level_zero(tmp_path, monkeypatch):
    """Asked for level 1, calibrate_model must still drop a nosleep model to
    level 0 — otherwise the probe carries --enable-sleep-mode and the /sleep in
    Phase 4 fails, wasting the whole run."""
    from logos_worker_node import calibration

    class _StopProbe(Exception):
        pass

    seen: dict = {}

    def _capture(plan, *_a, **_k):
        seen["plan"] = plan
        raise _StopProbe

    monkeypatch.setattr(calibration, "_kill_stale_vllm_workers", lambda: None)
    monkeypatch.setattr(calibration, "sample_vram_mb", lambda _i: 1000.0)
    monkeypatch.setattr(calibration, "spawn_vllm", _capture)

    with pytest.raises(_StopProbe):
        calibration.calibrate_model(
            {"model": "openai/gpt-oss-120b", "enable_sleep_mode": False},
            vllm_binary="vllm",
            port=18000,
            log_dir=tmp_path,
            sleep_level=1,
            ready_timeout_s=1.0,
        )

    assert seen["plan"]["enable_sleep_mode"] is False


def test_auto_calibration_refuses_to_run_against_an_unreadable_store(tmp_path, monkeypatch):
    """The boot-time path writes results back over the whole file too."""
    from logos_worker_node import calibration

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "model_profiles.yml").write_text("model_profiles:\n  org/model: {unterminated\n")
    corrupt = (state_dir / "model_profiles.yml").read_text()

    def _boom(*_a, **_k):
        raise AssertionError("must not calibrate when the store cannot be read")

    monkeypatch.setattr(calibration, "calibrate_with_tp_escalation", _boom)
    monkeypatch.setattr(calibration, "query_gpu_vram", lambda: [{"index": 0}])

    assert calibration.auto_calibrate_models(["org/model"], tmp_path / "config.yml", state_dir) == {}
    assert (state_dir / "model_profiles.yml").read_text() == corrupt
