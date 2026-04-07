"""Health check endpoints for AtlasML.

Provides a single health endpoint under `/api/v1/health/` that verifies the
application can still reach its Weaviate dependency and access the collections
required for AtlasML's core functionality.
"""

import logging

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from atlasml.clients.weaviate import CollectionNames, get_weaviate_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/health", tags=["health"])

REQUIRED_COLLECTIONS = (
    CollectionNames.EXERCISE.value,
    CollectionNames.COMPETENCY.value,
    CollectionNames.SEMANTIC_CLUSTER.value,
)


@router.get("/")
def health():
    """Return AtlasML health status including Weaviate availability details."""
    health_status = {
        "status": "ok",
        "components": {
            "api": {"status": "ok"},
            "weaviate": {"status": "ok", "collections": {}},
        },
    }

    try:
        client = get_weaviate_client()
    except Exception as exc:
        logger.exception("Failed to initialize Weaviate client", exc_info=exc)
        health_status["status"] = "error"
        health_status["components"]["weaviate"] = {
            "status": "error",
            "message": "Failed to initialize Weaviate client",
        }
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=health_status,
        )

    try:
        is_alive = client.is_alive()
    except Exception as exc:
        logger.exception("Weaviate liveness check failed", exc_info=exc)
        health_status["status"] = "error"
        health_status["components"]["weaviate"] = {
            "status": "error",
            "message": "Weaviate liveness check failed",
        }
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=health_status,
        )

    if not is_alive:
        health_status["status"] = "error"
        health_status["components"]["weaviate"] = {
            "status": "error",
            "message": "Weaviate is unreachable",
        }
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=health_status,
        )

    missing_collections = []
    for collection_name in REQUIRED_COLLECTIONS:
        try:
            exists = client.collection_exists(collection_name)
        except Exception as exc:
            logger.exception(
                "Failed to check required Weaviate collection %s",
                collection_name,
                exc_info=exc,
            )
            health_status["status"] = "error"
            health_status["components"]["weaviate"]["status"] = "error"
            health_status["components"]["weaviate"]["message"] = (
                f"Failed to check required collection {collection_name}"
            )
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content=health_status,
            )
        health_status["components"]["weaviate"]["collections"][collection_name] = {
            "status": "ok" if exists else "missing"
        }
        if not exists:
            missing_collections.append(collection_name)

    if missing_collections:
        health_status["status"] = "error"
        health_status["components"]["weaviate"]["status"] = "error"
        health_status["components"]["weaviate"]["message"] = (
            "Missing required collections: " + ", ".join(missing_collections)
        )
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=health_status,
        )

    try:
        client.can_read_collection(CollectionNames.COMPETENCY.value)
    except Exception as exc:
        logger.exception("Competency collection readability check failed", exc_info=exc)
        health_status["status"] = "error"
        health_status["components"]["weaviate"]["status"] = "error"
        health_status["components"]["weaviate"]["message"] = (
            "Competency collection is not readable"
        )
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=health_status,
        )

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=health_status,
    )
