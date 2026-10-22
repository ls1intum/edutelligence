"""The /internal/maintenance endpoints behind the statistics page's maintenance status."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from logos.dbutils.dbrequest import InternalReleaseCalibrationClaimRequest, InternalReleaseRecoveryRequest
from logos.logosnode_registry import MaintenanceBusyError
from logos.routers import internal as module


def _request(authorization: str = "Bearer secret") -> MagicMock:
    request = MagicMock()
    request.headers.get = lambda key, default="": authorization if key == "authorization" else default
    return request


@pytest.fixture
def coordinator(monkeypatch):
    service = MagicMock()
    monkeypatch.setattr(module, "_INTERNAL_SECRET", "secret")
    monkeypatch.setattr(module._main, "_maintenance_coordinator", service)
    monkeypatch.setattr(module, "_resolve_provider_name", lambda pid: f"worker-{pid}")
    return service


@pytest.mark.parametrize("secret, status", [(None, 403), ("secret", 401)])
async def test_both_endpoints_require_the_internal_secret(coordinator, monkeypatch, secret, status):
    monkeypatch.setattr(module, "_INTERNAL_SECRET", secret)
    body = InternalReleaseCalibrationClaimRequest(provider_id=1, claim_token="t")
    with pytest.raises(HTTPException) as exc:
        await module.internal_maintenance_status(_request("Bearer wrong"))
    assert exc.value.status_code == status
    with pytest.raises(HTTPException) as exc:
        await module.internal_release_calibration_claim(body, _request("Bearer wrong"))
    assert exc.value.status_code == status
    with pytest.raises(HTTPException) as exc:
        await module.internal_release_recovery(
            InternalReleaseRecoveryRequest(model_provider_id=31), _request("Bearer wrong")
        )
    assert exc.value.status_code == status
    coordinator.release_claim.assert_not_called()
    coordinator.release_recovery.assert_not_called()


async def test_status_fills_in_missing_provider_names(coordinator):
    coordinator.slot_status.return_value = {
        "limit": 1,
        "free": False,
        "calibrations": [{"provider_id": 3, "provider_name": None}],
        "benchmarks": [{"job_id": 7, "provider_id": 4, "provider_name": "named"}],
        "recoveries": [],
    }
    status = await module.internal_maintenance_status(_request())
    assert status["calibrations"][0]["provider_name"] == "worker-3"
    assert status["benchmarks"][0]["provider_name"] == "named"


async def test_status_without_coordinator_is_unavailable(coordinator, monkeypatch):
    monkeypatch.setattr(module._main, "_maintenance_coordinator", None)
    with pytest.raises(HTTPException) as exc:
        await module.internal_maintenance_status(_request())
    assert exc.value.status_code == 503


@pytest.mark.parametrize("error, status", [(LookupError("gone"), 404), (MaintenanceBusyError("live"), 409)])
async def test_release_maps_refusals_to_http_errors(coordinator, error, status):
    coordinator.release_claim = AsyncMock(side_effect=error)
    with pytest.raises(HTTPException) as exc:
        await module.internal_release_calibration_claim(
            InternalReleaseCalibrationClaimRequest(provider_id=1, claim_token="t"), _request()
        )
    assert exc.value.status_code == status


async def test_release_reports_whether_the_worker_confirmed(coordinator):
    coordinator.release_claim = AsyncMock(return_value={"released": True, "forced": True})
    result = await module.internal_release_calibration_claim(
        InternalReleaseCalibrationClaimRequest(provider_id=1, claim_token="t"), _request()
    )
    coordinator.release_claim.assert_awaited_once_with(1, "t")
    assert result["forced"] is True
    assert result["provider_id"] == 1
    assert "without confirmation" in result["message"]


@pytest.mark.parametrize("error, status", [(LookupError("gone"), 404), (MaintenanceBusyError("running"), 409)])
async def test_recovery_release_maps_refusals_to_http_errors(coordinator, error, status):
    coordinator.release_recovery = AsyncMock(side_effect=error)
    with pytest.raises(HTTPException) as exc:
        await module.internal_release_recovery(InternalReleaseRecoveryRequest(model_provider_id=31), _request())
    assert exc.value.status_code == status
    assert exc.value.detail == str(error)


@pytest.mark.parametrize("force", [False, True])
async def test_recovery_release_passes_force_through(coordinator, force):
    coordinator.release_recovery = AsyncMock(return_value={"released": True, "forced": force})
    result = await module.internal_release_recovery(
        InternalReleaseRecoveryRequest(model_provider_id=31, force=force), _request()
    )
    coordinator.release_recovery.assert_awaited_once_with(31, force)
    assert result["forced"] is force
    assert result["model_provider_id"] == 31


async def test_recovery_release_without_coordinator_is_unavailable(coordinator, monkeypatch):
    monkeypatch.setattr(module._main, "_maintenance_coordinator", None)
    with pytest.raises(HTTPException) as exc:
        await module.internal_release_recovery(InternalReleaseRecoveryRequest(model_provider_id=31), _request())
    assert exc.value.status_code == 503
