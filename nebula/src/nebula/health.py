import platform
import time
from datetime import datetime
from typing import Dict, Any, Optional, Callable, List, Union, Awaitable

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

# Track application start time for uptime calculation
START_TIME = time.time()


class ComponentHealth(BaseModel):
    """Health status of an individual system component."""

    status: str = Field(..., description="Status of the component (OK, WARNING, ERROR)")
    details: Optional[Dict[str, Any]] = Field(
        None, description="Additional details about component health"
    )

    class Config:
        json_schema_extra = {"properties": {"details": {"nullable": True}}}


class HealthCheck(BaseModel):
    """Response model for system health information."""

    status: str = Field(..., description="Overall system status")
    version: str = Field(..., description="Application version")
    uptime_seconds: int = Field(..., description="Application uptime in seconds")
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
                "version": "1.0.0",
                "uptime_seconds": 3600,
                "timestamp": "2025-03-06T12:00:00",
                "components": {
                    "system": {
                        "status": "OK",
                        "details": {"platform": "macOS-14.3.1-arm64"},
                    }
                },
            }
        }


# Component health check function type
ComponentCheckFunc = Callable[[], Union[Dict[str, Any], Awaitable[Dict[str, Any]]]]

# Store for registered component health check functions
_component_checks: Dict[str, ComponentCheckFunc] = {}


def register_component(name: str) -> Callable[[ComponentCheckFunc], ComponentCheckFunc]:
    """
    Decorator to register a component health check function.

    Args:
        name: The name of the component

    Returns:
        Decorator function
    """

    def decorator(func: ComponentCheckFunc) -> ComponentCheckFunc:
        _component_checks[name] = func
        return func

    return decorator


def create_health_router(
    app_version: str,
    prefix: str = "/health",
    tags: List[str] = ["healthcheck"],
    system_info: bool = True,
) -> APIRouter:
    """
    Create a health check router with standard health endpoints.

    Args:
        app_version: The version of the application
        prefix: URL prefix for the health endpoints (default: "/health")
        tags: OpenAPI tags for the health endpoints
        system_info: Whether to include system information in health check

    Returns:
        APIRouter: Router with health check endpoints
    """
    router = APIRouter(tags=tags, prefix=prefix)

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
        # Calculate uptime
        uptime = int(time.time() - START_TIME)

        # Collect component statuses
        components = {}
        overall_status = "OK"

        # Add system info if requested
        if system_info:
            components["system"] = ComponentHealth(
                status="OK",
                details={
                    "platform": platform.platform(),
                    "python_version": platform.python_version(),
                },
            )

        # Run all registered component checks
        for component_name, check_func in _component_checks.items():
            try:
                result = check_func()
                # Handle both sync and async functions
                if hasattr(result, "__await__"):
                    result = await result

                component_status = result.get("status", "ERROR")
                component_details = result.get("details")

                components[component_name] = ComponentHealth(
                    status=component_status,
                    details=component_details,
                )

                # If any component is not OK, the overall status is the worst status
                if component_status != "OK" and (
                    overall_status == "OK"
                    or (overall_status == "WARNING" and component_status == "ERROR")
                ):
                    overall_status = component_status
            except Exception as e:
                components[component_name] = ComponentHealth(
                    status="ERROR",
                    details={"error": str(e)},
                )
                overall_status = "ERROR"

        return HealthCheck(
            status=overall_status,
            version=app_version,
            uptime_seconds=uptime,
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

    return router
