from typing import List, Callable

from athena import _app
from .models import Exercise, Submission
from .storage import store_submission

def received_submissions():
    def decorator(func: Callable[[Exercise, List[Submission]], None]):
        @_app.post("/submissions")
        def wrapper(exercise: Exercise, submissions: List[Submission]):
            for submission in submissions:
                store_submission(submission)
            func(exercise, submissions)
        return wrapper
    return decorator