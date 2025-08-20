from contextlib import asynccontextmanager
from fastapi import FastAPI

from .container import get_container
from . import endpoints, authenticate  # should expose `routers`
from .module import request_to_module


def create_app() -> FastAPI:
    # Re-use the global singleton container so DI works everywhere consistently
    container = get_container()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.container = container
        try:
            yield
        finally:
            pass

    app = FastAPI(lifespan=lifespan)

    # Make the container available even before the lifespan starts (e.g. in __main__)
    app.state.container = container

    # Wire dependency_injector for functions that use @inject / Provide
    container.wire(modules=[authenticate, request_to_module])

    for r in getattr(endpoints, "routers", []):
        app.include_router(r)

    return app
