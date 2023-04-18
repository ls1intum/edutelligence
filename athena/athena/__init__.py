import os
from pathlib import Path
import inspect

import uvicorn

from .app import app
from .logger import logger
from .models import Exercise, Submission, Feedback
from .feedback_consumer import feedback_consumer
from .submissions_consumer import submissions_consumer
from .feedback_provider import feedback_provider


@app.get("/")
def read_root():
    return {"athena": "module"}


def start(port: int = 5001):
    """Start athena. Ensure to have `app` in your module main scope so that it can be imported."""
    logger.info("Starting athena module")

    importing_file = inspect.stack()[1].filename # one stack frame up to find it
    module_name = Path(importing_file).parent.name # get the parent directory name = module name

    if "PRODUCTION" in os.environ:
        logger.info("Running in PRODUCTION mode")
        uvicorn.run(f"{module_name}.__main__:app", host="0.0.0.0", port=port, proxy_headers=True)
    else:
        logger.warning("Running in DEVELOPMENT mode")
        uvicorn.run(f"{module_name}.__main__:app", host="0.0.0.0", port=port, reload=True)


# Expose the start function this way to ensure that modules have to import `app`, which uvicorn needs to discover in the module:
app.start = start


__all__ = [
    "Exercise",
    "Submission",
    "Feedback",
    "feedback_consumer",
    "submissions_consumer",
    "feedback_provider",
    "app"
]