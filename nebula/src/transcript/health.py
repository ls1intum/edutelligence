from fastapi import APIRouter, status
from fastapi.responses import Response, JSONResponse
from datetime import datetime
import time

router = APIRouter(prefix="/health", tags=["health"])

START_TIME = time.time()


@router.get("/", status_code=status.HTTP_200_OK)
async def health_check():
    """
    Full health check with uptime and timestamp.
    """
    uptime = int(time.time() - START_TIME)
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "status": "OK",
            "uptime_seconds": uptime,
            "timestamp": datetime.utcnow().isoformat(),
        },
    )


@router.get("/live", status_code=status.HTTP_200_OK)
async def liveness_check():
    """
    Simple liveness probe to confirm the app is running.
    """
    return Response(status_code=status.HTTP_200_OK, content=b"[]", media_type="application/json")
