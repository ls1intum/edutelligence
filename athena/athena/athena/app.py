from .logger import logger
import inspect
import os
from pathlib import Path

from fastapi import FastAPI
import uvicorn


class FastAPIWithStart(FastAPI):
    """
    Athena provides a FastAPI instance with an additional start method.
    We expose the start function this way to ensure that modules have to import `app`,
    which uvicorn needs to discover in the module.
    """
    def start(self, port: int = 5001) -> None:
        """Start Athena. You have to ensure to have `app` in your module main scope so that it can be imported."""
        logger.info("Starting athena module")

        importing_file = inspect.stack()[1].filename  # one stack frame up to find it
        module_name = Path(importing_file).parent.name  # get the parent directory name = module name

        if "PRODUCTION" in os.environ:
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


