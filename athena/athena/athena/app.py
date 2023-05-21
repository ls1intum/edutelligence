"""
The main app instance for your module. Try not to use the FastAPI functionality of the app instance directly.
Instead, use the decorators in the `athena` package.
The only exception is the `start` method, which is used to start the module.
"""
import uvicorn
from fastapi import FastAPI

from . import env
from .database import create_tables
from .logger import logger
from .module_config import get_module_config


class FastAPIWithStart(FastAPI):
    """
    Athena provides a FastAPI instance with an additional start method.
    We expose the start function this way to ensure that modules have to import `app`,
    which uvicorn needs to discover in the module.
    """
    def start(self) -> None:
        """Start Athena. You have to ensure to have `app` in your module main scope so that it can be imported."""
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
                reload_dirs=[conf.name, "../athena"],
            )


app: FastAPIWithStart = FastAPIWithStart()
