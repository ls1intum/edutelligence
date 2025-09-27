import uvicorn
from uvicorn.config import LOGGING_CONFIG
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from typing import Callable, Any

from .logger import logger
from .metadata import MetaDataMiddleware
from .experiment import ExperimentMiddleware
from .helpers.programming.repository_authorization_middleware import (
    init_repo_auth_middleware,
)

app = FastAPI()
app.add_middleware(MetaDataMiddleware)
app.add_middleware(ExperimentMiddleware)

init_repo_auth_middleware(app)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.error(
        "Validation error: %s \n Errors: %s\n Request body: %s",
        exc,
        exc.errors(),
        exc.body,
    )
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors()},
    )


def create_app(lifespan: Callable[[Any], Any]) -> FastAPI:
    """
    Applies the module-specific lifespan to the global app instance
    """
    app.router.lifespan_context = lifespan
    return app


def run_app(app_to_run: FastAPI, settings: "athena.settings.Settings"):
    """
    Starts the Uvicorn server for the given app and settings
    """
    app_to_run.state.settings = settings

    LOGGING_CONFIG["formatters"]["default"][
        "fmt"
    ] = "%(asctime)s %(levelname)s --- [%(name)s] : %(message)s"
    LOGGING_CONFIG["formatters"]["access"][
        "fmt"
    ] = "%(asctime)s %(levelname)s --- [%(name)s] : %(message)s"
    logger.info(f"Starting athena module '{settings.module.name}'")

    if settings.PRODUCTION:
        logger.info("Running in PRODUCTION mode")
        uvicorn.run(
            app_to_run, host="0.0.0.0", port=settings.module.port, proxy_headers=True
        )
    else:
        logger.warning("Running in DEVELOPMENT mode")
        uvicorn.run(
            f"{settings.module.name}.__main__:app",
            host="0.0.0.0",
            port=settings.module.port,
            reload=True,
            reload_dirs=[
                f"../{settings.module.name}/{settings.module.name}",
                "../athena/athena",
                "../llm_core/llm_core",
            ],
        )
