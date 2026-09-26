"""API endpoint for checking Iris service and module health."""

from __future__ import annotations

from typing import Callable

from fastapi import APIRouter, Depends, Request, Response, status

from iris.common.logging_config import get_logger
from iris.dependencies import TokenValidator
from iris.ingestion.worker import ingestion_worker
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


@router.get(
    "/",
    response_model=IrisHealthResponse,
    dependencies=[Depends(TokenValidator())],
)
def health(request: Request, response: Response) -> IrisHealthResponse:
    """
    Run health checks for all registered modules and return an overall status with metadata for each module.

    A health check doubles as an upstream announcement for the pull-based ingestion worker: an
    Artemis that includes its own base URL in the X-Artemis-Base-Url header registers itself as a
    queue to claim from, authenticated by the same api key this endpoint already requires. The
    header is optional, so older Artemis versions are simply never claimed from.
    """
    logger.debug("health_check invoked")
    announced_base_url = request.headers.get("X-Artemis-Base-Url")
    if announced_base_url:
        ingestion_worker.register_upstream(
            announced_base_url, request.headers.get("Authorization", "")
        )
    results = dict(check() for check in MODULES)
    logger.debug("Health check results: %s", results)
    overall_ok = all(m.status != ServiceStatus.DOWN for m in results.values())
    response.status_code = status.HTTP_200_OK
    return IrisHealthResponse(isHealthy=overall_ok, modules=results)
