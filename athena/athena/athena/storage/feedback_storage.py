from typing import Iterable, Union

from .models import DBFeedback
from athena.database import get_db
from athena.common.schemas import Feedback


def get_stored_feedback(exercise_id: int, submission_id: Union[int, None]) -> Iterable[Feedback]:
    """
    Returns a list of feedbacks for the given exercise in the given submission.
    If submission_id is None, returns all feedbacks for the given exercise.
    """
    with get_db() as db:
        query = db.query(DBFeedback).filter_by(exercise_id=exercise_id, is_suggestion=0)
        if submission_id is not None:
            query = query.filter_by(submission_id=submission_id)
        return (Feedback.from_orm(f) for f in query.all())


def store_feedback(feedback: Feedback):
    """Stores the given feedback."""
    with get_db() as db:
        db.add(DBFeedback(**feedback.dict(), is_suggestion=False))
        db.commit()


def get_stored_feedback_suggestions(exercise_id: str, submission_id: int) -> Iterable[Feedback]:
    """Returns a list of feedback suggestions for the given exercise in the given submission."""
    with get_db() as db:
        query = db.query(DBFeedback).filter_by(exercise_id=exercise_id, is_suggestion=True)
        if submission_id is not None:
            query = query.filter_by(submission_id=submission_id)
        return (Feedback(**f) for f in query.all())


def store_feedback_suggestion(feedback: Feedback):
    """Stores the given feedback as a suggestion."""
    with get_db() as db:
        db.add(DBFeedback(**feedback.dict(), is_suggestion=1))
        db.commit()
