from typing import List, Union
from .models import Submission, Feedback

def get_stored_submissions(exercise_id: int) -> List[Submission]:
    """Returns a list of submissions for the given exercise."""
    return []

def store_submission(submission: Submission):
    """Stores the given submission."""
    pass

def get_stored_feedback(exercise_id: int, submission_id: Union[int, None]) -> List[Feedback]:
    """
    Returns a list of feedbacks for the given exercise in the given submission.
    If submission_id is None, returns all feedbacks for the given exercise.
    """
    return []

def store_feedback(feedback: Feedback):
    """Stores the given feedback."""
    pass

def store_feedback_suggestion(feedback: Feedback):
    """Stores the given feedback as a suggestion."""
    pass

def get_stored_feedback_suggestions(exercise_id: str, submission_id: int) -> List[Feedback]:
    """Returns a list of feedback suggestions for the given exercise in the given submission."""
    return []