from functools import wraps
from typing import Callable, List

from .app import app
from .models import Exercise, Submission, Feedback


def feedback_provider(func: Callable[[Exercise, Submission], List[Feedback]]):
    @app.post("/feedback_suggestions")
    @wraps(func)
    def wrapper(exercise: Exercise, submission: Submission):
        return func(exercise, submission)

    return wrapper
