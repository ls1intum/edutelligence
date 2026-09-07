"""Pydantic models for health-check responses."""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from iris.common.boot_id import BOOT_ID


class ServiceStatus(str, Enum):
    UP = "UP"  # module up (ui: 🟢)
    WARN = "WARN"  # non-default variants missing (ui: 🟡)
    DEGRADED = "DEGRADED"  # some default variants invalid, none critical (ui: 🟠)
    DOWN = "DOWN"  # module down OR any critical pipeline invalid (ui: 🔴)


class ModuleStatus(BaseModel):
    """Represents the health status of a single module."""

    model_config = ConfigDict(populate_by_name=True)
    status: ServiceStatus
    error: Optional[str] = None
    meta_data: Optional[str] = Field(default=None, alias="metaData")


class IrisHealthResponse(BaseModel):
    """Overall health response, including all module statuses."""

    model_config = ConfigDict(populate_by_name=True)
    is_healthy: bool = Field(alias="isHealthy")
    boot_id: str = Field(default=BOOT_ID, alias="bootId")
    modules: dict[str, ModuleStatus] = Field(default_factory=dict)
