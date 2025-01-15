import os
import runpy
from pathlib import Path

from . import contextvars
from .app import app
from .schemas import ExerciseType, GradingCriterion, StructuredGradingInstruction, StructuredGradingCriterion
from .metadata import emit_meta, get_meta
from .experiment import get_experiment_environment
from .endpoints import submission_selector, submissions_consumer,feedback_feeder, feedback_consumer, feedback_provider, config_schema_provider, evaluation_provider  # type: ignore

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
    "contextvars",
    "app",
    "submission_selector",
    "submissions_consumer",
    "feedback_consumer",
    "feedback_provider",
    "feedback_feeder",
    "config_schema_provider",
    "evaluation_provider",
    "emit_meta",
    "get_meta",
    "get_experiment_environment",
    "ExerciseType",
    "GradingCriterion",
    "StructuredGradingInstruction",
    "StructuredGradingCriterion"
]
