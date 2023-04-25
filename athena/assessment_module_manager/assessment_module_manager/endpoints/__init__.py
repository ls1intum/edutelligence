from .consume_feedback_endpoint import consume_feedback
from .consume_submissions_endpoint import consume_submissions
from .feedback_suggestions_endpoint import get_feedback_suggestions
from .health_endpoint import get_health
from .modules_endpoint import get_modules
from .select_submission import select_submission

endpoints = [
    "get_health", "get_modules",
    "consume_submissions", "select_submission",
    "consume_feedback", "get_feedback_suggestions"
]
__all__ = ["endpoints"]
