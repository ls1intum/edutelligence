from typing import List, Iterable, Union, Type, Optional

from athena.database import get_db
from athena.schemas import Submission


def get_stored_submissions(
        submission_cls: Type[Submission], exercise_id: int, only_ids: Union[List[int], None] = None
) -> Iterable[Submission]:
    """
    Returns a list of submissions for the given exercise and submission ids.
    If only_ids is None, returns all submissions for the given exercise.
    """
    db_submission_cls = submission_cls.get_model_class()
    with get_db() as db:
        query = db.query(db_submission_cls).filter_by(exercise_id=exercise_id)
        if only_ids is not None:
            query = query.filter(db_submission_cls.id.in_(only_ids))  # type: ignore
        return (s.to_schema() for s in query.all())


def get_stored_submission_meta(submission: Submission) -> Optional[dict]:
    """Returns the stored metadata associated with the submission."""
    db_submission_cls = submission.__class__.get_model_class()
    with get_db() as db:
        return db.query(db_submission_cls.meta).filter_by(id=submission.id).scalar()  # type: ignore


def store_submissions(submissions: List[Submission]):
    """Stores the given submissions, all at once."""
    with get_db() as db:
        for s in submissions:
            db.merge(s.to_model())
        db.commit()

def store_submission(submission: Submission):
    """Stores the given submission."""
    store_submissions([submission])
