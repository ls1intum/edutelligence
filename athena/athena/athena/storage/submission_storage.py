from typing import List, Iterable, Union

from .models import DBSubmission
from athena.database import get_db
from athena.common.schemas import Submission


def get_stored_submissions(exercise_id: int, only_ids: Union[List[int], None] = None) -> Iterable[Submission]:
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