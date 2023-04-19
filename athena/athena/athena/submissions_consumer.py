from functools import wraps
from typing import List, Callable

from .app import app
from .models import Exercise, Submission
from .storage import store_submission


def submissions_consumer(func: Callable[[Exercise, List[Submission]], None]):
    @app.post("/submissions")
    @wraps(func)
    def wrapper(exercise: Exercise, submissions: List[Submission]):
        for submission in submissions:
            store_submission(submission)
        func(exercise, submissions)

    return wrapper
