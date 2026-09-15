"""Tests for the process boot id reported by the health endpoint."""

from iris.common.boot_id import BOOT_ID
from iris.web.routers.health.health_model import IrisHealthResponse


def test_health_response_carries_the_stable_process_boot_id():
    first = IrisHealthResponse(isHealthy=True).model_dump(by_alias=True)
    second = IrisHealthResponse(isHealthy=False).model_dump(by_alias=True)

    assert first["bootId"] == BOOT_ID
    assert first["bootId"] == second["bootId"]
