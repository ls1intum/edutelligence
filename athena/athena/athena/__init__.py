import os
from pathlib import Path
import runpy

from .app import app
from .models import Exercise, Submission, Feedback
from .feedback_consumer import feedback_consumer
from .submissions_consumer import submissions_consumer
from .feedback_provider import feedback_provider


@app.get("/")
def module_health():
    """The root endpoint is used as the health check for the module."""
    return {"status": "ok"}


def run_module():
    """Helper function for nice poetry scripts to start athena modules."""
    module_parent_path = Path(os.getcwd())
    module_name = module_parent_path.name
    runpy.run_module(module_name, run_name="__main__")


__all__ = [
    "Exercise",
    "Submission",
    "Feedback",
    "feedback_consumer",
    "submissions_consumer",
    "feedback_provider",
    "app"
]
