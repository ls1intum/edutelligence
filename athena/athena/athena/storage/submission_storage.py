from typing import List, Iterable, Union, Type, Optional

from athena.contextvars import get_lms_url
from athena.database import get_db
from athena.schemas import Submission


def count_stored_submissions(
        submission_cls: Type[Submission], exercise_id: int, lms_url: Optional[str] = None
) -> int:
    """Returns the number of submissions for the given exercise."""

    if lms_url is None:
        lms_url = get_lms_url()

    db_submission_cls = submission_cls.get_model_class()
    with get_db() as db:
        return db.query(db_submission_cls).filter_by(exercise_id=exercise_id,
                                                     lms_url=lms_url).count()  # type: ignore


def get_stored_submissions(
        submission_cls: Type[Submission], exercise_id: int, only_ids: Union[List[int], None] = None,
        lms_url: Optional[str] = None
) -> Iterable[Submission]:
    """
    Returns a list of submissions for the given exercise and submission ids.
    If only_ids is None, returns all submissions for the given exercise.
    """

    if lms_url is None:
        lms_url = get_lms_url()

    db_submission_cls = submission_cls.get_model_class()
    with get_db() as db:
        query = db.query(db_submission_cls).filter_by(exercise_id=exercise_id, lms_url=lms_url)
        if only_ids is not None:
            query = query.filter(db_submission_cls.id.in_(only_ids))  # type: ignore
        return (s.to_schema() for s in query.all())


def get_stored_submission_meta(submission: Submission, lms_url: Optional[str] = None) -> Optional[dict]:
    """Returns the stored metadata associated with the submission."""

    if lms_url is None:
        lms_url = get_lms_url()

    db_submission_cls = submission.__class__.get_model_class()
    with get_db() as db:
        return db.query(db_submission_cls.meta).filter_by(id=submission.id,  # type: ignore
                                                          lms_url=lms_url).scalar()


def store_submissions(submissions: List[Submission], lms_url: Optional[str] = None):
    """Stores the given submissions, all at once."""

    if lms_url is None:
        lms_url = get_lms_url()

    with get_db() as db:
        for s in submissions:
            submission_model = s.to_model()
            submission_model.lms_url = lms_url
            db.merge(submission_model)
        db.commit()


def store_submission(submission: Submission, lms_url: Optional[str] = None):
    """Stores the given submission."""
    store_submissions([submission], lms_url)
