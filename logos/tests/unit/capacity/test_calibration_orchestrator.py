"""Targeted tests for CalibrationOrchestrator selection logic."""

from __future__ import annotations

from typing import Any

from logos.capacity.calibration_orchestrator import CalibrationConfig, CalibrationOrchestrator
from logos.sdi.models import ModelProfile


class _StubFacade:
    def __init__(self, profiles: dict[str, ModelProfile], configured: list[str]) -> None:
        self._profiles = profiles
        self._configured = configured

    def get_configured_models(self, provider_id: int) -> list[str]:  # noqa: ARG002
        return list(self._configured)

    def get_worker_capabilities(self, provider_id: int) -> list[str]:  # noqa: ARG002
        return list(self._configured)

    def get_model_profiles(self, provider_id: int) -> dict[str, ModelProfile]:  # noqa: ARG002
        return dict(self._profiles)

    def get_provider_name(self, provider_id: int) -> str:  # noqa: ARG002
        return f"worker-{provider_id}"


class _StubRegistry:
    def __init__(self, node_health: dict[int, dict] | None = None) -> None:
        self._node_health = node_health or {}

    def has_received_first_status(self, provider_id: int) -> bool:  # noqa: ARG002
        return True

    def peek_runtime_snapshot(self, provider_id: int) -> dict | None:
        nh = self._node_health.get(provider_id)
        return {"runtime": {"node_health": nh}} if nh is not None else {"runtime": {}}


def _make_orchestrator(
    profiles: dict[str, ModelProfile],
    configured: list[str],
    node_health: dict[int, dict] | None = None,
) -> CalibrationOrchestrator:
    facade: Any = _StubFacade(profiles, configured)
    registry: Any = _StubRegistry(node_health=node_health)
    return CalibrationOrchestrator(registry=registry, facade=facade, config=CalibrationConfig())


def test_find_uncalibrated_skips_models_with_sleep_mode_disabled():
    """Regression for prod 2026-06-04: gpt-oss-120b on deimama is configured
    with enable_sleep_mode=false, so sleep_l1_transient_host_ram_mb can
    never be measured. Without recognizing the sleep_mode_disabled flag,
    the orchestrator picks the model every maintenance window, the worker
    spawns a doomed vLLM lane, and Phase 4 (POST /sleep) fails. With the
    flag honored, the orchestrator treats the sleep fields as N/A and
    moves on to a model that actually needs calibration."""
    profile = ModelProfile(
        model_name="openai/gpt-oss-120b",
        base_residency_mb=91203.0,
        # Both sleep-related fields are intentionally None because the
        # worker config forbids sleeping this model.
        sleeping_residual_mb=None,
        sleep_l1_transient_host_ram_mb=None,
        sleep_mode_disabled=True,
    )
    orch = _make_orchestrator(
        profiles={"openai/gpt-oss-120b": profile},
        configured=["openai/gpt-oss-120b"],
    )

    assert orch._find_uncalibrated_model(provider_id=15) is None


def test_find_uncalibrated_still_targets_sleep_capable_models():
    """A model whose sleep_mode_disabled is False/None and that is missing
    sleep_l1_transient_host_ram_mb still needs calibration."""
    profile = ModelProfile(
        model_name="microsoft/Phi-4-reasoning",
        base_residency_mb=47113.0,
        sleeping_residual_mb=1329.0,
        sleep_l1_transient_host_ram_mb=None,
        sleep_mode_disabled=False,
    )
    orch = _make_orchestrator(
        profiles={"microsoft/Phi-4-reasoning": profile},
        configured=["microsoft/Phi-4-reasoning"],
    )

    assert orch._find_uncalibrated_model(provider_id=15) == "microsoft/Phi-4-reasoning"


def test_find_uncalibrated_picks_sleep_capable_over_sleep_disabled_neighbor():
    """Mixed worker: one sleep-disabled (fully measured for what it can
    measure) and one sleep-capable but uncalibrated. Orchestrator must
    skip the first and target the second."""
    sleep_disabled = ModelProfile(
        model_name="openai/gpt-oss-120b",
        base_residency_mb=91203.0,
        sleep_mode_disabled=True,
    )
    needs_calib = ModelProfile(
        model_name="microsoft/Phi-4-reasoning",
        base_residency_mb=None,
    )
    orch = _make_orchestrator(
        profiles={
            "openai/gpt-oss-120b": sleep_disabled,
            "microsoft/Phi-4-reasoning": needs_calib,
        },
        configured=["openai/gpt-oss-120b", "microsoft/Phi-4-reasoning"],
    )

    assert orch._find_uncalibrated_model(provider_id=15) == "microsoft/Phi-4-reasoning"


def test_find_uncalibrated_skips_calibration_unsupported_models():
    """Regression for prod 2026-06-04: Qwen/Qwen-Image-Edit is configured on
    deioma but it's a diffusion model — vLLM rejects it with 'Invalid
    repository ID or local directory specified' at every load attempt.
    Once the worker classifies it as calibration_unsupported, the
    orchestrator must skip it on every subsequent maintenance window
    instead of re-issuing start_calibration and watching the same
    identity-level error reproduce."""
    profile = ModelProfile(
        model_name="Qwen/Qwen-Image-Edit",
        # Nothing measured — the model never loaded.
        base_residency_mb=None,
        calibration_unsupported=True,
        calibration_unsupported_reason="invalid-repo-id",
    )
    orch = _make_orchestrator(
        profiles={"Qwen/Qwen-Image-Edit": profile},
        configured=["Qwen/Qwen-Image-Edit"],
    )

    assert orch._find_uncalibrated_model(provider_id=15) is None


def test_find_uncalibrated_picks_neighbor_when_one_is_calibration_unsupported():
    """Mixed worker: one model on the unsupported list (skip) plus one
    genuinely uncalibrated neighbor (target)."""
    unsupported = ModelProfile(
        model_name="Qwen/Qwen-Image-Edit",
        calibration_unsupported=True,
        calibration_unsupported_reason="invalid-repo-id",
    )
    needs_calib = ModelProfile(
        model_name="microsoft/Phi-4-reasoning",
        base_residency_mb=None,
    )
    orch = _make_orchestrator(
        profiles={
            "Qwen/Qwen-Image-Edit": unsupported,
            "microsoft/Phi-4-reasoning": needs_calib,
        },
        configured=["Qwen/Qwen-Image-Edit", "microsoft/Phi-4-reasoning"],
    )

    assert orch._find_uncalibrated_model(provider_id=15) == "microsoft/Phi-4-reasoning"


def test_pick_calibration_target_skips_unhealthy_worker():
    """Regression for deioma 2026-06-04: when a worker reports
    node_health.healthy=False (e.g. Ceph-backed HF cache returning EIO),
    the orchestrator must NOT schedule calibration on it. Without this
    skip, the master would fire start_calibration once per minute, the
    worker would refuse each one, and the logs would fill with
    'refusing start_calibration' warnings every cycle."""
    needs_calib = ModelProfile(
        model_name="microsoft/Phi-4-reasoning",
        base_residency_mb=None,
    )
    orch = _make_orchestrator(
        profiles={"microsoft/Phi-4-reasoning": needs_calib},
        configured=["microsoft/Phi-4-reasoning"],
        node_health={15: {"healthy": False, "reason_code": "filesystem-eio"}},
    )
    orch._facade.provider_ids = lambda: [15]

    assert orch._pick_calibration_target() is None


def test_pick_calibration_target_resumes_after_node_recovers():
    """Once a worker reports node_health.healthy=True again, the
    orchestrator should pick up the previously-skipped uncalibrated
    model on the very next tick."""
    needs_calib = ModelProfile(
        model_name="microsoft/Phi-4-reasoning",
        base_residency_mb=None,
    )
    orch = _make_orchestrator(
        profiles={"microsoft/Phi-4-reasoning": needs_calib},
        configured=["microsoft/Phi-4-reasoning"],
        node_health={15: {"healthy": True}},
    )
    orch._facade.provider_ids = lambda: [15]
    # Stub doesn't implement get_all_provider_lane_signals; bypass that
    # check so we exercise just the node-health gate.
    orch._provider_has_active_requests = lambda provider_id: False

    assert orch._pick_calibration_target() == (15, "microsoft/Phi-4-reasoning")
