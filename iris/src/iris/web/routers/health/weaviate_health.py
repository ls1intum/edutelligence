"""Health check logic for the Weaviate vector database module."""

from __future__ import annotations

import logging

from requests import RequestException, Timeout
from weaviate.exceptions import (
    UnexpectedStatusCodeException,
    WeaviateConnectionError,
)

from iris.config import settings
from iris.vector_database.database import VectorDatabase
from iris.web.routers.health.health_model import ModuleStatus, ServiceStatus

log = logging.getLogger(__name__)


def check_weaviate_status() -> list[tuple[str, ModuleStatus]]:
    """Check the connection and readiness status of the Weaviate instance."""
    module_name = "Weaviate Vector Database"
    url = f"https://{settings.weaviate.host}:{settings.weaviate.port}/v1"
    status_obj = ModuleStatus(status=ServiceStatus.DOWN, meta_data=url)

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

    return [(module_name, status_obj)]
