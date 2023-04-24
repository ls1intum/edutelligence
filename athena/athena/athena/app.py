"""
The main app instance for your module. Try not to use the FastAPI functionality of the app instance directly.
Instead, use the decorators in the `athena` package.
The only exception is the `start` method, which is used to start the module.
"""
import os

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI

from .logger import logger


class FastAPIWithStart(FastAPI):
    """
    Athena provides a FastAPI instance with an additional start method.
    We expose the start function this way to ensure that modules have to import `app`,
    which uvicorn needs to discover in the module.
    """
    def start(self) -> None:
        """Start Athena. You have to ensure to have `app` in your module main scope so that it can be imported."""
        logger.info("Starting athena module")

        load_dotenv(".env")

        module_name = os.environ["MODULE_NAME"]
        port = int(os.environ["PORT"])

        if "PRODUCTION" in os.environ and os.environ["PRODUCTION"] == "1":
            logger.info("Running in PRODUCTION mode")
            uvicorn.run(f"{module_name}.__main__:app", host="0.0.0.0", port=port, proxy_headers=True)
        else:
            logger.warning("Running in DEVELOPMENT mode")
            uvicorn.run(
                f"{module_name}.__main__:app",
                host="0.0.0.0",
                port=port,
                # reload on changes to the module or the athena package
                reload=True,
                reload_dirs=[module_name, "../athena"],
            )


app: FastAPIWithStart = FastAPIWithStart()
