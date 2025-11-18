"""
The main app instance for your module. Try not to use the FastAPI functionality of the app instance directly.
Instead, use the decorators in the `athena` package.
The only exception is the `start` method, which is used to start the module.
"""
import uvicorn
from uvicorn.config import LOGGING_CONFIG
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from . import env
from .database import create_tables
from .logger import logger
from .module_config import get_module_config
from .metadata import MetaDataMiddleware
from .experiment import ExperimentMiddleware
from .helpers.programming.repository_authorization_middleware import init_repo_auth_middleware


class FastAPIWithStart(FastAPI):
    """
    Athena provides a FastAPI instance with an additional start method.
    We expose the start function this way to ensure that modules have to import `app`,
    which uvicorn needs to discover in the module.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.add_middleware(MetaDataMiddleware)
        self.add_middleware(ExperimentMiddleware)


    def start(self) -> None:
        """Start Athena. You have to ensure to have `app` in your module main scope so that it can be imported."""
        LOGGING_CONFIG["formatters"]["default"]["fmt"] = "%(asctime)s %(levelname)s --- [%(name)s] : %(message)s"
        LOGGING_CONFIG["formatters"]["access"]["fmt"] = "%(asctime)s %(levelname)s --- [%(name)s] : %(message)s"
        logger.info("Starting athena module")

        conf = get_module_config()

        logger.debug("Creating database tables")
        create_tables(conf.type)

        if env.PRODUCTION:
            logger.info("Running in PRODUCTION mode")
            uvicorn.run(f"{conf.name}.__main__:app", host="0.0.0.0", port=conf.port, proxy_headers=True)
        else:
            logger.warning("Running in DEVELOPMENT mode")
            uvicorn.run(
                f"{conf.name}.__main__:app",
                host="0.0.0.0",
                port=conf.port,
                # reload on changes to the module or the athena package
                reload=True,
                # Reload only on source changes (not .venv to prevent high CPU usage, see https://github.com/encode/uvicorn/issues/338#issuecomment-642298366)
                reload_dirs=["../" + conf.name + "/" + conf.name, "../athena/athena"],
            )


app: FastAPIWithStart = FastAPIWithStart(
    title="Athena Module API",
    description="API for Athena assessment module",
)

# Initialize the repository authorization middleware for programming modules (also initializing it for other modules does not hurt)
init_repo_auth_middleware(app)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.error("Validation error: %s \n Errors: %s\n Request body: %s", exc, exc.errors(), exc.body)
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors()},
    )
