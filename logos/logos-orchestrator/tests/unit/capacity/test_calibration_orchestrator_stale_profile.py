"""A stale calibration keeps serving but is picked for re-calibration."""

from __future__ import annotations

from unittest.mock import MagicMock

from logos.capacity.calibration_orchestrator import CalibrationOrchestrator
from logos.sdi.models import ModelProfile


def _calibrated(stale: bool | None) -> ModelProfile:
    return ModelProfile(
        model_name="org/model",
        base_residency_mb=15000.0,
        sleeping_residual_mb=600.0,
        sleep_l1_transient_host_ram_mb=100.0,
        residency_source="calibrated",
        kv_cache_to_max_model_len_pairs=[{"kv_mb": 4096.0, "max_model_len": 32768}],
        calibration_stale=stale,
    )


def _orch(profile: ModelProfile) -> CalibrationOrchestrator:
    orch = CalibrationOrchestrator.__new__(CalibrationOrchestrator)
    registry = MagicMock()
    registry.peek_runtime_snapshot.return_value = {"runtime": {"devices": {"mode": "nvidia"}}}
    facade = MagicMock()
    facade.get_configured_models.return_value = ["org/model"]
    facade.get_model_profiles.return_value = {"org/model": profile}
    orch._registry = registry
    orch._facade = facade
    return orch


def test_fresh_calibration_needs_nothing():
    assert _orch(_calibrated(False))._provider_has_uncalibrated_models(1) is False
    assert _orch(_calibrated(None))._provider_has_uncalibrated_models(1) is False


def test_stale_calibration_is_recalibrated():
    assert _orch(_calibrated(True))._provider_has_uncalibrated_models(1) is True


def test_stale_marker_survives_serialization():
    assert _calibrated(True).to_dict()["calibration_stale"] is True
    assert _calibrated(None).to_dict()["calibration_stale"] is None
