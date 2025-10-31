"""API endpoint for checking Iris service and module health."""

from __future__ import annotations

from logging import getLogger
from typing import Callable

from fastapi import APIRouter, Depends, Response, status

from iris.dependencies import TokenValidator
from iris.web.routers.health.health_model import (
    IrisHealthResponse,
    ModuleStatus,
)
from iris.web.routers.health.weaviate_health import check_weaviate_status

router = APIRouter(prefix="/api/v1/health", tags=["health"])
logging = getLogger(__name__)
HealthCheckCallable = Callable[[], list[tuple[str, ModuleStatus]]]

MODULES: list[HealthCheckCallable] = [
    check_weaviate_status,
]


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
    results = {k: v for check in MODULES for (k, v) in check()}
    logging.debug("Health check results: %s", results)
    overall_ok = all(m.healthy for m in results.values())
    if overall_ok:
        response.status_code = status.HTTP_200_OK
    else:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return IrisHealthResponse(modules=results)
