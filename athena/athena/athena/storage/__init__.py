from typing import List, Union, Iterable

from .database import get_db
from .models import DBExercise, DBSubmission, DBFeedback
from ..schemas import Submission, Feedback


def get_stored_submissions(exercise_id: int, only_ids: List[int] | None = None) -> Iterable[Submission]:
    """
    Returns a list of submissions for the given exercise and submission ids.
    If only_ids is None, returns all submissions for the given exercise.
    """
    with get_db() as db:
        query = db.query(DBSubmission).filter_by(exercise_id=exercise_id)
        if only_ids is not None:
            query = query.filter(DBSubmission.id.in_(only_ids))
        return (Submission.from_orm(s) for s in query.all())


def store_submissions(submissions: List[Submission]):
    """Stores the given submissions, all at once."""
    with get_db() as db:
        db_submissions = [DBSubmission(**s.dict()) for s in submissions]
        for s in db_submissions:
            db.merge(s)
        db.commit()


def store_submission(submission: Submission):
    """Stores the given submission."""
    store_submissions([submission])


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
        db.add(DBFeedback(**feedback.dict(), is_suggestion=0))
        db.commit()


def get_stored_feedback_suggestions(exercise_id: str, submission_id: int) -> Iterable[Feedback]:
    """Returns a list of feedback suggestions for the given exercise in the given submission."""
    with get_db() as db:
        query = db.query(DBFeedback).filter_by(exercise_id=exercise_id, is_suggestion=1)
        if submission_id is not None:
            query = query.filter_by(submission_id=submission_id)
        return (Feedback(**f) for f in query.all())


def store_feedback_suggestion(feedback: Feedback):
    """Stores the given feedback as a suggestion."""
    with get_db() as db:
        db.add(DBFeedback(**feedback.dict(), is_suggestion=1))
        db.commit()
