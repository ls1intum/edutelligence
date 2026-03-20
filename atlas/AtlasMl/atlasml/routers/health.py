"""Health check endpoints for AtlasML.

Provides a single health endpoint under `/api/v1/health/` that verifies the
application can still reach its Weaviate dependency and access the collections
required for AtlasML's core functionality.
"""

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from atlasml.clients.weaviate import CollectionNames, get_weaviate_client

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
        health_status["status"] = "error"
        health_status["components"]["weaviate"] = {
            "status": "error",
            "message": f"Failed to initialize Weaviate client: {exc}",
        }
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=health_status,
        )

    if not client.is_alive():
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
        exists = client.client.collections.exists(collection_name)
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
        client.get_all_embeddings(CollectionNames.COMPETENCY.value)
    except Exception as exc:
        health_status["status"] = "error"
        health_status["components"]["weaviate"]["status"] = "error"
        health_status["components"]["weaviate"]["message"] = (
            f"Competency collection is not readable: {exc}"
        )
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=health_status,
        )

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=health_status,
    )
