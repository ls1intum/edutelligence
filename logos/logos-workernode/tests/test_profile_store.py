"""How a calibration result is layered over a node's existing profile.

A calibration run measures what it can reach and leaves the rest None; the
merge must keep what is already known without hiding a fresh measurement.
"""

from __future__ import annotations

import pytest

from logos_worker_node.calibration import CalibrationResult, _build_vllm_cmd, merge_profile, result_to_profile_dict

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


def test_merge_clears_a_stale_sleep_measurement():
    """A run reports sleeping_residual_mb null exactly when the model must not
    be slept here: the sleep phases were skipped, or they ran but failed
    verification (sleep_mode_disabled=True). Keeping the old number hides
    that, and survives an enable_sleep_mode flip back to true — the freshness
    check sees a value, declines to re-calibrate, and the planner sizes a wake
    from a configuration that no longer exists."""
    prior = {"base_residency_mb": 98945.0, "sleeping_residual_mb": 1400.0, "sleep_mode_disabled": False}

    merged = merge_profile(prior, {"base_residency_mb": 99000.0, "sleeping_residual_mb": None})

    assert merged["sleeping_residual_mb"] is None
    assert merged["sleep_mode_disabled"] is False, "still a field the probe does not own"


def test_merge_sleep_mode_disabled_verdict_overrides_stored_value():
    """When the probe exercised the sleep phases, its verdict (True/False)
    overrides the stored value: a new failure sets True, and a successful
    re-verification clears a stale True (e.g. after a vLLM upgrade). A None
    verdict (phases skipped at level 0) lets the stored value — e.g. the
    operator gate's flag — stand."""
    merged = merge_profile({"sleep_mode_disabled": False}, {"sleep_mode_disabled": True})
    assert merged["sleep_mode_disabled"] is True, "measured failure wins"

    merged = merge_profile({"sleep_mode_disabled": True}, {"sleep_mode_disabled": False})
    assert merged["sleep_mode_disabled"] is False, "measured success clears a stale flag"

    merged = merge_profile({"sleep_mode_disabled": True}, {"sleep_mode_disabled": None})
    assert merged["sleep_mode_disabled"] is True, "no verdict keeps the stored value"


def test_merge_keeps_the_sleep_transient_of_a_level_it_did_not_run():
    """Unlike the residual, the per-level host-RAM transients are each only
    measurable by their own level — an L1 run saying nothing about L2 is not
    a statement that L2 has no transient."""
    prior = {"sleep_l1_transient_host_ram_mb": 900.0, "sleep_l2_transient_host_ram_mb": 7000.0}

    merged = merge_profile(prior, {"sleep_l1_transient_host_ram_mb": 950.0, "sleep_l2_transient_host_ram_mb": None})

    assert merged["sleep_l1_transient_host_ram_mb"] == 950.0
    assert merged["sleep_l2_transient_host_ram_mb"] == 7000.0


def test_merge_without_a_prior_entry():
    assert merge_profile(None, {"base_residency_mb": 1.0}) == {"base_residency_mb": 1.0}


def test_merge_does_not_mutate_the_prior_entry():
    prior = {"base_residency_mb": 1.0}
    merge_profile(prior, {"base_residency_mb": 2.0})
    assert prior == {"base_residency_mb": 1.0}


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


def test_a_result_carries_the_sleeping_host_ram_measurement():
    """The number the cache planner's sleep reserve is sized on. It was being
    measured from lane telemetry and stored, but calibration never produced a
    figure of its own — so a model that had not yet slept on this worker had
    no reserve at all, and the cache was free to take the RAM it would need."""
    result = CalibrationResult(
        model="org/model",
        tensor_parallel_size=1,
        gpu_devices="0",
        kv_cache_sent_mb=2048.0,
        success=True,
        base_residency_mb=12345.0,
        sleeping_residual_mb=512.0,
        host_ram_residual_mb=16384.44,
    )

    assert result_to_profile_dict(result)["host_ram_residual_mb"] == 16384.4


def test_a_nosleep_result_leaves_the_sleeping_host_ram_unknown():
    """A level-0 run never sleeps the model, so it has nothing to say about
    what sleeping would cost — null, not zero, which would read as "measured,
    and it holds nothing"."""
    result = CalibrationResult(
        model="openai/gpt-oss-120b",
        tensor_parallel_size=2,
        gpu_devices="0,1",
        kv_cache_sent_mb=8192.0,
        success=True,
        base_residency_mb=98945.0,
        sleeping_residual_mb=None,
        host_ram_residual_mb=None,
    )

    assert result_to_profile_dict(result)["host_ram_residual_mb"] is None


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
