from typing import Iterable, Union, Type, Optional, List

from athena.database import get_db
from athena.schemas import Feedback


def get_stored_feedback(
        feedback_cls: Type[Feedback], exercise_id: int, submission_id: Union[int, None], artemis_url: str = None
) -> Iterable[Feedback]:
    """
    Returns a list of feedbacks for the given exercise in the given submission.
    If submission_id is None, returns all feedbacks for the given exercise.
    """

    if artemis_url is None:
        artemis_url = get_artemis_url()

    db_feedback_cls = feedback_cls.get_model_class()
    with get_db() as db:
        query = db.query(db_feedback_cls).filter_by(exercise_id=exercise_id, is_suggestion=0, artemis_url=artemis_url)
        if submission_id is not None:
            query = query.filter_by(submission_id=submission_id)
        return (f.to_schema() for f in query.all())


def get_stored_feedback_meta(feedback: Feedback, artemis_url: str = None) -> Optional[dict]:
    """Returns the stored metadata associated with the feedback."""

    if artemis_url is None:
        artemis_url = get_artemis_url()

    db_feedback_cls = feedback.__class__.get_model_class()
    with get_db() as db:
        return db.query(db_feedback_cls.meta).filter_by(id=feedback.id,
                                                        artemis_url=artemis_url).scalar()  # type: ignore


def store_feedback(feedback: Feedback, is_lms_id=False, artemis_url: str = None) -> Feedback:
    """Stores the given LMS feedback.

    Args:
        feedback (Feedback): The feedback to store.
        is_lms_id (bool, optional): Whether the feedback's ID is an LMS ID. Defaults to False.
        artemis_url (str, optional): The URL of the Artemis instance that issued the query
    Returns:
        Feedback: The stored feedback with its internal ID assigned.
    """

    if artemis_url is None:
        artemis_url = get_artemis_url()

    db_feedback_cls = feedback.__class__.get_model_class()
    with get_db() as db:
        lms_id = None
        if is_lms_id:
            lms_id = feedback.id
            internal_id = db.query(db_feedback_cls.id).filter_by(lms_id=lms_id,
                                                                 artemis_url=artemis_url).scalar()  # type: ignore
            feedback.id = internal_id

        stored_feedback_model = db.merge(feedback.to_model(lms_id=lms_id))
        db.commit()
        return stored_feedback_model.to_schema()


def get_stored_feedback_suggestions(
        feedback_cls: Type[Feedback], exercise_id: int, submission_id: int, artemis_url: str = None
) -> Iterable[Feedback]:
    """Returns a list of feedback suggestions for the given exercise in the given submission."""

    if artemis_url is None:
        artemis_url = get_artemis_url()

    db_feedback_cls = feedback_cls.get_model_class()
    with get_db() as db:
        query = db.query(db_feedback_cls).filter_by(exercise_id=exercise_id, is_suggestion=True,
                                                    artemis_url=artemis_url)
        if submission_id is not None:
            query = query.filter_by(submission_id=submission_id)
        return (f.to_schema() for f in query.all())


def store_feedback_suggestions(feedbacks: List[Feedback], artemis_url: str = None) -> List[Feedback]:
    """Stores the given feedbacks as a suggestions.

    Returns:
        List[Feedback]: The stored feedback suggestions with their internal IDs assigned.
    """

    if artemis_url is None:
        artemis_url = get_artemis_url()

    stored_feedbacks: List[Feedback] = []
    with get_db() as db:
        for feedback in feedbacks:
            feedback_model = feedback.to_model(is_suggestion=True)
            feedback_model.artemis_url = artemis_url
            feedback_model = db.merge(feedback_model)
            db.flush()  # Ensure the ID is generated now
            stored_feedbacks.append(feedback_model.to_schema())
        db.commit()
    return stored_feedbacks


def store_feedback_suggestion(feedback: Feedback, artemis_url: str = None):
    """Stores the given feedback as a suggestion."""
    store_feedback_suggestions([feedback], artemis_url)
