"""API endpoint for checking Iris service and module health."""

from __future__ import annotations

from logging import getLogger
from typing import Callable

from fastapi import APIRouter, Depends, Response, status

from iris.dependencies import TokenValidator
from iris.web.routers.health.health_model import (
    IrisHealthResponse,
    ModuleStatus,
    ServiceStatus,
)
from iris.web.routers.health.Pipelines.pipeline_health import check_pipelines_health
from iris.web.routers.health.weaviate_health import check_weaviate_status

router = APIRouter(prefix="/api/v1/health", tags=["health"])
logging = getLogger(__name__)
HealthCheckCallable = Callable[[], tuple[str, ModuleStatus]]

MODULES: list[HealthCheckCallable] = [check_weaviate_status, check_pipelines_health]


@router.get(
    "/",
    response_model=IrisHealthResponse,
    dependencies=[Depends(TokenValidator())],
)
def health(response: Response) -> IrisHealthResponse:
    """
    Run health checks for all registered modules and return an overall status.

    Sets the HTTP status code to 200 OK if all modules are healthy,
    otherwise 503 Service Unavailable.
    """
    logging.debug("health_check invoked")
    results = dict(check() for check in MODULES)
    logging.debug("Health check results: %s", results)
    overall_ok = all(m.status != ServiceStatus.DOWN for m in results.values())
    response.status_code = status.HTTP_200_OK
    return IrisHealthResponse(isHealthy=overall_ok, modules=results)
