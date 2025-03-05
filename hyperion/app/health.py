import platform
import time
from datetime import datetime
from typing import Dict, Any, Optional

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from app.project_meta import project_meta
from app.settings import settings

# Create a router for health-related endpoints
router = APIRouter(tags=["healthcheck"], prefix="/health")

# Track application start time for uptime calculation
START_TIME = time.time()


class ComponentHealth(BaseModel):
    """Health status of an individual system component."""

    status: str = Field(..., description="Status of the component (OK, WARNING, ERROR)")
    details: Optional[Dict[str, Any]] = Field(
        None, description="Additional details about component health"
    )


class HealthCheck(BaseModel):
    """Response model for system health information."""

    status: str = Field(..., description="Overall system status")
    version: str = Field(..., description="Application version")
    uptime_seconds: int = Field(..., description="Application uptime in seconds")
    environment: str = Field(..., description="Execution environment")
    timestamp: datetime = Field(
        default_factory=datetime.now, description="Time when health check was performed"
    )
    components: Dict[str, ComponentHealth] = Field(
        default_factory=dict, description="Status of individual components"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "status": "OK",
                "version": "0.1.0",
                "uptime_seconds": 3600,
                "environment": "production",
                "timestamp": "2025-03-06T12:00:00",
                "components": {
                    "system": {
                        "status": "OK",
                        "details": {"platform": "Linux-5.15.0-x86_64"},
                    }
                },
            }
        }


@router.get(
    "",
    summary="Perform a Health Check",
    response_description="Return HTTP Status Code 200 (OK) with system health information",
    status_code=status.HTTP_200_OK,
    response_model=HealthCheck,
)
async def get_health() -> HealthCheck:
    """
    ## Perform a Health Check

    Endpoint to perform a health check on the service. This endpoint can be used by:

    - Container orchestrators like Docker or Kubernetes to ensure service health
    - Load balancers to determine if the service should receive traffic
    - Monitoring tools to track service availability

    The endpoint returns information about system health including uptime and version.

    Returns:
        HealthCheck: Health status information
    """
    # Determine environment
    env = "production"
    if settings.DISABLE_AUTH:
        env = "development"

    # Calculate uptime
    uptime = int(time.time() - START_TIME)

    # Get system info
    components = {
        "system": ComponentHealth(
            status="OK",
            details={
                "platform": platform.platform(),
                "python_version": platform.python_version(),
            },
        )
    }

    return HealthCheck(
        status="OK",
        version=project_meta.version,
        uptime_seconds=uptime,
        environment=env,
        components=components,
    )


@router.get(
    "/live",
    summary="Liveness Check",
    response_description="Simple liveness check that always returns OK if service is running",
    status_code=status.HTTP_200_OK,
)
async def get_liveness():
    """
    Simple liveness check endpoint that returns 200 OK when the service is running.
    This endpoint is lightweight and can be called frequently by infrastructure.
    """
    return {"status": "OK"}
