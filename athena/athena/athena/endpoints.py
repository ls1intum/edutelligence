import inspect
from typing import TypeVar, Callable, List, Annotated
from functools import wraps

from athena.app import app
from athena.authenticate import authenticated
from athena.logger import logger
from athena.schemas import Exercise, Submission, Feedback
from athena.storage import get_stored_submission_meta, get_stored_exercise_meta, get_stored_feedback_meta, \
    store_exercise, store_feedback, store_feedback_suggestions, store_submissions, get_stored_submissions
    

E = TypeVar('E', bound=Exercise)
S = TypeVar('S', bound=Submission)
F = TypeVar('F', bound=Feedback)


module_responses = {
    403: {
        "description": "API secret is invalid - set the environment variable SECRET and the X-API-Secret header "
                       "to the same value",
    }
}


def submissions_consumer(func: Callable[[E, List[S]], None]):
    """
    Receive submissions from the Assessment Module Manager.
    The submissions consumer is usually called whenever the deadline for an exercise is reached.
    """
    exercise_type = inspect.signature(func).parameters["exercise"].annotation
    submission_type = inspect.signature(func).parameters["submissions"].annotation.__args__[0]

    @app.post("/submissions", responses=module_responses)
    @authenticated
    def wrapper(
            exercise: exercise_type,
            submissions: List[submission_type]):
        # Retrieve existing metadata for the exercise and submissions
        exercise.meta.update(get_stored_exercise_meta(exercise) or {})
        submissions_dict = {s.id: s for s in submissions}
        if submissions:
            stored_submissions = get_stored_submissions(submissions[0].__class__, exercise.id, [s.id for s in submissions])
            for stored_submission in stored_submissions:
                if stored_submission.id in submissions_dict:
                    submissions_dict[stored_submission.id].meta.update(stored_submission.meta)
        submissions = list(submissions_dict.values())

        # Call the actual consumer
        func(exercise, submissions)

    return wrapper


def submission_selector(func: Callable[[E, List[S]], S]):
    """
    Receive an exercise and some (not necessarily all!) submissions from the Assessment Module Manager and
    return the submission that should ideally be assessed next.
    If the selector returns None, the LMS will select a random submission in the end.
    """
    exercise_type = inspect.signature(func).parameters["exercise"].annotation
    submission_type = inspect.signature(func).parameters["submissions"].annotation.__args__[0]

    @app.post("/select_submission", responses=module_responses)
    @authenticated
    def wrapper(
            exercise: exercise_type,
            submission_ids: List[int]) -> int:
        # The wrapper handles only transmitting submission IDs for efficiency, but the actual selection logic
        # only works with the full submission objects.

        exercise.meta.update(get_stored_exercise_meta(exercise) or {})

        # Get the full submission objects
        submissions = list(get_stored_submissions(submission_type, exercise.id, submission_ids))
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


def feedback_consumer(func: Callable[[E, S, F], None]):
    """
    Receive feedback from the Assessment Module Manager.
    The feedback consumer is usually called whenever the LMS gets feedback from a tutor.
    """
    exercise_type = inspect.signature(func).parameters["exercise"].annotation
    submission_type = inspect.signature(func).parameters["submission"].annotation
    feedback_type = inspect.signature(func).parameters["feedback"].annotation

    @app.post("/feedback", responses=module_responses)
    @authenticated
    def wrapper(
            exercise: exercise_type,
            submission: submission_type,
            feedback: feedback_type):
        # Retrieve existing metadata for the exercise, submission and feedback
        exercise.meta.update(get_stored_exercise_meta(exercise) or {})
        submission.meta.update(get_stored_submission_meta(submission) or {})
        feedback.meta.update(get_stored_feedback_meta(feedback) or {})

        store_feedback(feedback)

        # Call the actual consumer
        func(exercise, submission, feedback)

    return wrapper


def feedback_provider(func: Callable[[E, S], List[F]]):
    """
    Provide feedback to the Assessment Module Manager.
    The feedback provider is usually called whenever the tutor requests feedback for a submission in the LMS.
    """
    exercise_type = inspect.signature(func).parameters["exercise"].annotation
    submission_type = inspect.signature(func).parameters["submission"].annotation

    @app.post("/feedback_suggestions", responses=module_responses)
    @authenticated
    def wrapper(
            exercise: exercise_type,
            submission: submission_type):
        # Retrieve existing metadata for the exercise, submission and feedback
        exercise.meta.update(get_stored_exercise_meta(exercise) or {})
        submission.meta.update(get_stored_submission_meta(submission) or {})

        store_exercise(exercise)
        store_submissions([submission])

        # Call the actual provider
        feedbacks = func(exercise, submission)
        store_feedback_suggestions(feedbacks)

        return feedbacks
    return wrapper
