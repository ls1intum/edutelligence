from typing import Iterable, Union, Type, Optional, List

from athena.contextvars import get_lms_url
from athena.database import get_db
from athena.schemas import Feedback


def get_stored_feedback(
        feedback_cls: Type[Feedback], exercise_id: int, submission_id: Union[int, None], lms_url: Optional[str] = None
) -> Iterable[Feedback]:
    """
    Returns a list of feedbacks for the given exercise in the given submission.
    If submission_id is None, returns all feedbacks for the given exercise.
    """

    if lms_url is None:
        lms_url = get_lms_url()

    db_feedback_cls = feedback_cls.get_model_class()
    with get_db() as db:
        query = db.query(db_feedback_cls).filter_by(exercise_id=exercise_id, is_suggestion=False, lms_url=lms_url)
        if submission_id is not None:
            query = query.filter_by(submission_id=submission_id)
        return (f.to_schema() for f in query.all())


def get_stored_feedback_meta(feedback: Feedback, lms_url: Optional[str] = None) -> Optional[dict]:
    """Returns the stored metadata associated with the feedback."""

    if lms_url is None:
        lms_url = get_lms_url()

    db_feedback_cls = feedback.__class__.get_model_class()
    with get_db() as db:
        return db.query(db_feedback_cls.meta).filter_by(id=feedback.id,  # type: ignore
                                                        lms_url=lms_url).scalar()


def store_feedback(feedback: Feedback, is_lms_id=False, lms_url: Optional[str] = None) -> Feedback:
    """Stores the given LMS feedback.

    Args:
        feedback (Feedback): The feedback to store.
        is_lms_id (bool, optional): Whether the feedback's ID is an LMS ID. Defaults to False.
        lms_url (str, optional): The URL of the LMS instance that issued the query
    Returns:
        Feedback: The stored feedback with its internal ID assigned.
    """

    if lms_url is None:
        lms_url = get_lms_url()

    db_feedback_cls = feedback.__class__.get_model_class()
    with get_db() as db:
        lms_id = None
        if is_lms_id:
            lms_id = feedback.id
            internal_id = db.query(db_feedback_cls.id).filter_by(lms_id=lms_id,  # type: ignore
                                                                 lms_url=lms_url).scalar()
            feedback.id = internal_id

        stored_feedback_model = db.merge(feedback.to_model(lms_id=lms_id, lms_url=lms_url))
        db.commit()
        return stored_feedback_model.to_schema()


def get_stored_feedback_suggestions(
        feedback_cls: Type[Feedback], exercise_id: int, submission_id: int, lms_url: Optional[str] = None
) -> Iterable[Feedback]:
    """Returns a list of feedback suggestions for the given exercise in the given submission."""

    if lms_url is None:
        lms_url = get_lms_url()

    db_feedback_cls = feedback_cls.get_model_class()
    with get_db() as db:
        query = db.query(db_feedback_cls).filter_by(exercise_id=exercise_id, is_suggestion=True,
                                                    lms_url=lms_url)
        if submission_id is not None:
            query = query.filter_by(submission_id=submission_id)
        return (f.to_schema() for f in query.all())


def store_feedback_suggestions(feedbacks: List[Feedback], lms_url: Optional[str] = None) -> List[Feedback]:
    """Stores the given feedbacks as a suggestions.

    Returns:
        List[Feedback]: The stored feedback suggestions with their internal IDs assigned.
    """

    if lms_url is None:
        lms_url = get_lms_url()

    stored_feedbacks: List[Feedback] = []
    with get_db() as db:
        for feedback in feedbacks:
            feedback_model = feedback.to_model(is_suggestion=True)
            feedback_model.lms_url = lms_url
            feedback_model = db.merge(feedback_model)
            db.flush()  # Ensure the ID is generated now
            stored_feedbacks.append(feedback_model.to_schema())
        db.commit()
    return stored_feedbacks


def store_feedback_suggestion(feedback: Feedback, lms_url: Optional[str] = None):
    """Stores the given feedback as a suggestion."""
    store_feedback_suggestions([feedback], lms_url)
