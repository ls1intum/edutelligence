"""Health check logic for the Weaviate vector database module."""

from __future__ import annotations

from requests import RequestException, Timeout
from weaviate.exceptions import (
    UnexpectedStatusCodeException,
    WeaviateConnectionError,
)

from iris.common.logging_config import get_logger
from iris.config import settings
from iris.vector_database.database import VectorDatabase
from iris.web.routers.health.health_model import ModuleStatus, ServiceStatus

log = get_logger(__name__)


def check_weaviate_status() -> tuple[str, ModuleStatus]:
    """Check the connection and readiness status of the Weaviate instance.

    An unavailable Weaviate is reported as DEGRADED rather than DOWN: chat and the other pipelines still answer
    without lecture and FAQ lookups, and a DOWN module would make Artemis show Iris as unavailable to everyone.
    """
    module_name = "Weaviate Vector Database"
    url = f"http://{settings.weaviate.host}:{settings.weaviate.port}/v1"
    status_obj = ModuleStatus(status=ServiceStatus.DEGRADED, metaData=url)

    try:
        client = VectorDatabase().client
        if client.is_ready():
            status_obj.status = ServiceStatus.UP
        else:
            status_obj.error = "Weaviate reported not ready."
    except (WeaviateConnectionError, UnexpectedStatusCodeException) as exc:
        # Errors explicitly raised by the Weaviate client
        log.error(
            "Weaviate client error during health check",
            exc_info=True,
        )
        status_obj.error = f"Weaviate error: {exc}"
    except (RequestException, Timeout) as exc:
        # Network layer issues (requests)
        log.error(
            "Network error during Weaviate health check",
            exc_info=True,
        )
        status_obj.error = f"Network error: {exc}"
    except Exception as exc:
        log.error("Unexpected error during Weaviate health check", exc_info=True)
        status_obj.error = f"Weaviate error: {exc}"

    return module_name, status_obj
