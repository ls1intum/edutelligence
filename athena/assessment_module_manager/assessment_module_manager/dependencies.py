from fastapi import Request, HTTPException
from .settings import Settings
from .module_registry import ModuleRegistry


def get_settings(request: Request) -> Settings:
    settings = getattr(request.app.state, "settings", None)
    if settings is None:
        raise HTTPException(
            status_code=500, detail="Settings not initialized on app.state."
        )
    return settings


def get_registry(request: Request) -> ModuleRegistry:
    registry = getattr(request.app.state, "registry", None)
    if registry is None:
        raise HTTPException(
            status_code=500, detail="Module registry not initialized on app.state."
        )
    return registry
