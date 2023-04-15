import os

from fastapi import FastAPI
import uvicorn

from .models import Exercise, Submission, Feedback
from .feedback_consumer import feedback_consumer
from .submissions_consumer import submissions_consumer
from .feedback_provider import feedback_provider
from .logger import logger

_app = FastAPI()

@_app.get("/")
def read_root():
    return {"athene": "module"}

def start():
    logger.info("Starting athena module")
    if "PRODUCTION" in os.environ:
        logger.info("Running in PRODUCTION mode")
        uvicorn.run(_app, host="127.0.0.1", port=8000, proxy_headers=True)
    else:
        logger.warning("Running in DEVELOPMENT mode")
        uvicorn.run(_app, host="127.0.0.1", port=8000, reload=True)

__all__ = [
    "Exercise",
    "Submission",
    "Feedback",
    "feedback_consumer",
    "submissions_consumer",
    "feedback_provider",
    "start"
]