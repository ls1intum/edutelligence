import inspect
from functools import wraps
from typing import TypeVar, Callable, List

from athena.app import app
from athena.logger import logger
from athena.schemas import Exercise, Submission, Feedback
from athena.storage import store_feedback, get_stored_submissions, store_exercise, store_submissions

E = TypeVar('E', bound=Exercise)
S = TypeVar('S', bound=Submission)
F = TypeVar('F', bound=Feedback)

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


def submission_selector(func: Callable[[E, List[S]], S]):
    """
    Receive an exercise and some (not necessarily all!) submissions from the Assessment Module Manager and
    return the submission that should ideally be assessed next.
    If the selector returns None, the LMS will select a random submission in the end.
    """
    exercise_type = func.__annotations__["exercise"]

    @app.post("/select_submission")
    @wraps_except_annotations
    def wrapper(exercise: exercise_type, submission_ids: List[int]) -> int:
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


def submissions_consumer(func: Callable[[E, List[S]], None]):
    """
    Receive submissions from the Assessment Module Manager and automatically store them in the database.
    The submissions consumer is usually called whenever the deadline for an exercise is reached.
    """

    @app.post("/submissions")
    @wraps(func)
    def wrapper(exercise, submissions):
        store_exercise(exercise)
        store_submissions(submissions)
        return func(exercise, submissions)

    return wrapper


def feedback_consumer(func: Callable[[E, S, F], None]):
    """
    Receive feedback from the Assessment Module Manager and automatically store it in the database.
    The feedback consumer is usually called whenever the LMS gets feedback from a tutor.
    """

    @app.post("/feedback")
    @wraps(func)
    def wrapper(exercise, submission, feedback):
        store_feedback(feedback)
        return func(exercise, submission, feedback)

    return wrapper


def feedback_provider(func: Callable[[E, S], List[F]]):
    """
    Provide feedback to the Assessment Module Manager.
    The feedback provider is usually called whenever the tutor requests feedback for a submission in the LMS.
    """
    @app.post("/feedback_suggestions")
    @wraps(func)
    def wrapper(exercise, submission):
        return func(exercise, submission)

    return wrapper
