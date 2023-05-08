from typing import Iterable, Union, Type

from athena.database import get_db
from athena.schemas import Feedback


def get_stored_feedback(
        feedback_cls: Type[Feedback], exercise_id: int, submission_id: Union[int, None]
) -> Iterable[Feedback]:
    """
    Returns a list of feedbacks for the given exercise in the given submission.
    If submission_id is None, returns all feedbacks for the given exercise.
    """
    db_feedback_cls = feedback_cls.get_model_class()
    with get_db() as db:
        query = db.query(db_feedback_cls).filter_by(exercise_id=exercise_id, is_suggestion=0)
        if submission_id is not None:
            query = query.filter_by(submission_id=submission_id)
        return (f.to_schema() for f in query.all())


def store_feedback(feedback: Feedback):
    """Stores the given feedback."""
    with get_db() as db:
        db.add(feedback.to_model())
        db.commit()


def get_stored_feedback_suggestions(
        feedback_cls: Type[Feedback], exercise_id: str, submission_id: int
) -> Iterable[Feedback]:
    """Returns a list of feedback suggestions for the given exercise in the given submission."""
    db_feedback_cls = feedback_cls.get_model_class()
    with get_db() as db:
        query = db.query(db_feedback_cls).filter_by(exercise_id=exercise_id, is_suggestion=True)
        if submission_id is not None:
            query = query.filter_by(submission_id=submission_id)
        return (f.to_schema() for f in query.all())


def store_feedback_suggestion(feedback: Feedback):
    """Stores the given feedback as a suggestion."""
    with get_db() as db:
        db.add(feedback.to_model(is_suggestion=True))
        db.commit()
