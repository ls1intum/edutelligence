"""Pydantic models for health-check responses."""

from pydantic import BaseModel, Field


class ModuleStatus(BaseModel):
    """Represents the health status of a single module."""

    healthy: bool
    url: str | None = None
    error: str | None = None


class IrisHealthResponse(BaseModel):
    """Overall health response, including all module statuses."""

    modules: dict[str, ModuleStatus] = Field(default_factory=dict)
