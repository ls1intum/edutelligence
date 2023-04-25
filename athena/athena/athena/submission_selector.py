"""
This module provides a decorator for submission selectors.
"""
from functools import wraps
from typing import Callable, List

from .app import app
from .models import Exercise, Submission
from .storage import get_stored_submissions


def submission_selector(func: Callable[[Exercise, List[Submission]], Submission]):
    """
    Receive an exercise and some (not necessarily all!) submissions from the Assessment Module Manager and
    return the submission that should ideally be assessed next.
    If the selector returns None, the Assessment Module Manager will select a random submission.
    """
    @app.post("/select_submission")
    @wraps(func)
    def wrapper(exercise: Exercise, submission_ids: List[int]) -> int:
        # The wrapper handles only transmitting submission IDs for efficiency, but the actual selection logic
        # only works with the full submission objects.

        if not submission_ids:
            # Nothing to select from
            return -1

        # Get the full submission objects
        submissions = get_stored_submissions(exercise.id, submission_ids)
        # Select the submission
        submission = func(exercise, submissions)

        if submission is None:
            return -1
        return submission.id
    return wrapper
