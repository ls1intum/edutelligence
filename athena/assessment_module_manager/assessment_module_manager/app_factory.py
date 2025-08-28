from contextlib import asynccontextmanager
from fastapi import FastAPI
from pathlib import Path

from .settings import Settings
from . import endpoints
from .module_registry import ModuleRegistry


def create_app() -> FastAPI:

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings = Settings()

        modules_config_path = Path(__file__).parent.parent / "modules.ini"
        registry = ModuleRegistry(config_path=modules_config_path)

        settings.initialize_secrets(modules=registry.get_all_modules())

        # 4. Attach both to the application state
        app.state.settings = settings
        app.state.registry = registry
        try:
            yield
        finally:
            pass

    app = FastAPI(lifespan=lifespan)

    for r in getattr(endpoints, "routers", []):
        app.include_router(r)

    return app
