from fastapi import Request
from .settings import Settings


def get_settings(request: Request) -> Settings:
    settings = getattr(request.app.state, "settings", None)
    if settings is None:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=500, detail="Settings not initialized on app.state."
        )
    return settings


def get_registry(request: Request):
    # If you have a registry/provider for modules, surface it here
    settings = get_settings(request)
    return settings if hasattr(settings, "settings") else None
