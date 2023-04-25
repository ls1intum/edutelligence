"""
This module provides a decorator for submission selectors.
"""
import inspect
from functools import wraps
from typing import Callable, List

from .app import app
from .logger import logger
from .schemas import Exercise, Submission
from .storage import get_stored_submissions


def wraps_except_annotations(func: Callable) -> Callable:
    """
    This is a replacement for functools.wraps that ignores annotations.
    This is necessary when the signature of the wrapper function is different from the signature of the wrapped function
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)
    wrapper.__signature__ = inspect.signature(func)
    return wrapper


def submission_selector(func: Callable[[Exercise, List[Submission]], Submission]):
    """
    Receive an exercise and some (not necessarily all!) submissions from the Assessment Module Manager and
    return the submission that should ideally be assessed next.
    If the selector returns None, the LMS will select a random submission in the end.
    """
    @app.post("/select_submission")
    @wraps_except_annotations
    def wrapper(exercise: Exercise, submission_ids: List[int]) -> int:
        # The wrapper handles only transmitting submission IDs for efficiency, but the actual selection logic
        # only works with the full submission objects.

        # Get the full submission objects
        submissions = list(get_stored_submissions(exercise.id, submission_ids))
        if len(submission_ids) != len(submissions):
            logger.warning("Not all submissions were found in the database! "
                           "Have you sent all submissions to the submission consumer before?")
        if not submissions:
            # Nothing to select from
            return -1
        # Select the submission
        submission = func(exercise, submissions)

        if submission is None:
            return -1
        return submission.id

    return wrapper
