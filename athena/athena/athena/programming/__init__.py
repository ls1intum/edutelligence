from typing import Callable, List
from functools import wraps

from .schemas import Exercise, Submission, Feedback
from ..common.submissions_consumer import submissions_consumer as common_submissions_consumer
from ..common.submission_selector import submission_selector as common_submission_selector
from ..common.feedback_consumer import feedback_consumer as common_feedback_consumer
from ..common.feedback_provider import feedback_provider as common_feedback_provider


@wraps(common_submissions_consumer, assigned=("__name__", "__doc__"))
def submissions_consumer(func: Callable[[Exercise, Submission], None]):
    return common_submissions_consumer(func)


@wraps(common_submission_selector, assigned=("__name__", "__doc__"))
def submission_selector(func: Callable[[Exercise, Submission], Submission]):
    return common_submission_selector(func)


@wraps(common_feedback_consumer, assigned=("__name__", "__doc__"))
def feedback_consumer(func: Callable[[Exercise, Submission, Feedback], None]):
    return common_feedback_consumer(func)


@wraps(common_feedback_provider, assigned=("__name__", "__doc__"))
def feedback_provider(func: Callable[[Exercise, Submission], List[Feedback]]):
    return common_feedback_provider(func)
