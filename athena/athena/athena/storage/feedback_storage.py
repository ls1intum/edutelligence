from typing import Iterable, Union, Type, Optional, List

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


def get_stored_feedback_meta(feedback: Feedback) -> Optional[dict]:
    """Returns the stored metadata associated with the feedback."""
    db_feedback_cls = feedback.__class__.get_model_class()
    with get_db() as db:
        return db.query(db_feedback_cls.meta).filter_by(id=feedback.id).scalar()  # type: ignore


def store_feedback(feedback: Feedback):
    """Stores the given feedback."""
    with get_db() as db:
        db.merge(feedback.to_model())
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


def store_feedback_suggestions(feedbacks: List[Feedback]) -> List[Feedback]:
    """Stores the given feedbacks as a suggestions.

    Returns:
        List[Feedback]: The stored feedbacks with their IDs assigned.
    """
    stored_feedback_models: List[Feedback] = []
    with get_db() as db:
        for feedback in feedbacks:
            stored_feedback_model = db.merge(feedback.to_model(is_suggestion=True))
            db.flush() # Ensure the ID is generated now
            stored_feedback_models.append(stored_feedback_model.to_schema())
        db.commit()
    return stored_feedback_models


def store_feedback_suggestion(feedback: Feedback):
    """Stores the given feedback as a suggestion."""
    store_feedback_suggestions([feedback])
