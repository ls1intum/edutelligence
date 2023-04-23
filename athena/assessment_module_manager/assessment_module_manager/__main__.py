import os

import uvicorn

from .app import app
from .endpoints import endpoints
from .logger import logger


def main():
    logger.info("Starting assessment module manager")

    if "PRODUCTION" in os.environ:
        logger.info("Running in PRODUCTION mode")
        uvicorn.run("assessment_module_manager.__main__:app", host="0.0.0.0", port=5000)
    else:
        logger.warning("Running in DEVELOPMENT mode")
        uvicorn.run("assessment_module_manager.__main__:app", host="0.0.0.0", port=5000, reload=True)


# Add things to __all__ just to mark them as important to import
__all__ = ["app", "endpoints", "main"]
if __name__ == "__main__":
    main()
