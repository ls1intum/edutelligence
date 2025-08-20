from fastapi import Depends, Request


def get_container(request: Request):
    return request.app.state.container


def get_settings(container=Depends(get_container)):
    return container.settings()


def get_registry(container=Depends(get_container)):
    # If you have a registry/provider for modules, surface it here
    return container.settings() if hasattr(container, "settings") else None
