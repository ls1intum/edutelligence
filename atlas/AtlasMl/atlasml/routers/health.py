"""Health check endpoints for AtlasML.

Provides a minimal liveness probe under `/api/v1/health/` returning HTTP 200.
This router is safe to use for container orchestrator probes and uptime checks.
"""

from fastapi import APIRouter, Response, status

router = APIRouter(prefix="/api/v1/health", tags=["health"])


@router.get("/")
def health():
    """Return an empty JSON list with 200 OK as a simple liveness response."""
    return Response(
        status_code=status.HTTP_200_OK,
        content=b"[]",
        media_type="application/json",
    )
