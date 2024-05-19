from typing import List, Iterable, Union, Type, Optional

from athena.contextvars import get_artemis_url
from athena.database import get_db
from athena.schemas import Submission


def count_stored_submissions(
        submission_cls: Type[Submission], exercise_id: int, artemis_url: str = None
) -> int:
    """Returns the number of submissions for the given exercise."""

    if artemis_url is None:
        artemis_url = get_artemis_url()

    db_submission_cls = submission_cls.get_model_class()
    with get_db() as db:
        return db.query(db_submission_cls).filter_by(exercise_id=exercise_id,
                                                     artemis_url=artemis_url).count()  # type: ignore


def get_stored_submissions(
        submission_cls: Type[Submission], exercise_id: int, only_ids: Union[List[int], None] = None,
        artemis_url: str = None
) -> Iterable[Submission]:
    """
    Returns a list of submissions for the given exercise and submission ids.
    If only_ids is None, returns all submissions for the given exercise.
    """

    if artemis_url is None:
        artemis_url = get_artemis_url()

    db_submission_cls = submission_cls.get_model_class()
    with get_db() as db:
        query = db.query(db_submission_cls).filter_by(exercise_id=exercise_id, artemis_url=artemis_url)
        if only_ids is not None:
            query = query.filter(db_submission_cls.id.in_(only_ids))  # type: ignore
        return (s.to_schema() for s in query.all())


def get_stored_submission_meta(submission: Submission, artemis_url: str = None) -> Optional[dict]:
    """Returns the stored metadata associated with the submission."""

    if artemis_url is None:
        artemis_url = get_artemis_url()

    db_submission_cls = submission.__class__.get_model_class()
    with get_db() as db:
        return db.query(db_submission_cls.meta).filter_by(id=submission.id,
                                                          artemis_url=artemis_url).scalar()  # type: ignore


def store_submissions(submissions: List[Submission], artemis_url: str = None):
    """Stores the given submissions, all at once."""

    if artemis_url is None:
        artemis_url = get_artemis_url()

    with get_db() as db:
        for s in submissions:
            submission_model = s.to_model()
            submission_model.artemis_url = artemis_url
            db.merge(submission_model)
        db.commit()


def store_submission(submission: Submission, artemis_url: str = None):
    """Stores the given submission."""
    store_submissions([submission], artemis_url)
