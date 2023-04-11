from typing import List
from .models import Submission, Feedback

def get_stored_submissions(exercise_id: str) -> List[Submission]:
    """Returns a list of submissions for the given exercise."""
    return []

def store_submission(submission: Submission):
    """Stores the given submission."""
    pass

def get_stored_feedback(exercise_id: str) -> List[Feedback]:
    """Returns a list of feedbacks for the given exercise."""
    return []

def store_feedback(feedback: Feedback):
    """Stores the given feedback."""
    pass