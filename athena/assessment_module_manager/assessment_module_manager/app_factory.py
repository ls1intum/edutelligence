from contextlib import asynccontextmanager
from fastapi import FastAPI

from .settings import Settings
from . import endpoints  # should expose `routers`


def create_app() -> FastAPI:

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Initialize settings
        settings = Settings()
        app.state.settings = settings
        try:
            yield
        finally:
            pass

    app = FastAPI(lifespan=lifespan)

    for r in getattr(endpoints, "routers", []):
        app.include_router(r)

    return app
