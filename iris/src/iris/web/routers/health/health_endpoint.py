"""API endpoint for checking Iris service and module health."""

from __future__ import annotations

import uuid
from typing import Callable

from fastapi import APIRouter, Depends, Response, status

from iris.common.logging_config import get_logger
from iris.dependencies import TokenValidator
from iris.web.routers.health.health_model import (
    IrisHealthResponse,
    ModuleStatus,
    ServiceStatus,
)
from iris.web.routers.health.Pipelines.pipeline_health import check_pipelines_health
from iris.web.routers.health.weaviate_health import check_weaviate_status

router = APIRouter(prefix="/api/v1/health", tags=["health"])
logger = get_logger(__name__)
HealthCheckCallable = Callable[[], tuple[str, ModuleStatus]]

MODULES: list[HealthCheckCallable] = [check_weaviate_status, check_pipelines_health]

# Minted once per process, so it is constant while this Iris process runs and changes after a restart. Artemis uses it
# to detect a genuine restart and fail any ingestion that was in flight across it.
INSTANCE_ID = str(uuid.uuid4())


@router.get(
    "/",
    response_model=IrisHealthResponse,
    dependencies=[Depends(TokenValidator())],
)
def health(response: Response) -> IrisHealthResponse:
    """
    Run health checks for all registered modules and return an overall status with metadata for each module.
    """
    logger.debug("health_check invoked")
    results = dict(check() for check in MODULES)
    logger.debug("Health check results: %s", results)
    overall_ok = all(m.status != ServiceStatus.DOWN for m in results.values())
    response.status_code = status.HTTP_200_OK
    return IrisHealthResponse(
        isHealthy=overall_ok, modules=results, instanceId=INSTANCE_ID
    )
