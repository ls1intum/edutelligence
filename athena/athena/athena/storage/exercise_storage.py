from typing import List, Iterable, Optional, Type

from athena.contextvars import get_lms_url
from athena.database import get_db
from athena.schemas import Exercise


def get_stored_exercises(exercise_cls: Type[Exercise], lms_url: Optional[str] = None, only_ids: Optional[List[int]] = None) -> \
Iterable[Exercise]:
    """
    Returns a list of exercises for the given exercise type and exercise ids.
    If only_ids is None, returns all exercises for the given exercise type.
    """

    if lms_url is None:
        lms_url = get_lms_url()

    db_exercise_cls = exercise_cls.get_model_class()
    with get_db() as db:
        query = db.query(db_exercise_cls)
        if only_ids is not None:
            query = query.filter(db_exercise_cls.id.in_(only_ids))  # type: ignore
        query = query.filter(db_exercise_cls.lms_url == lms_url)  # type: ignore
        return (e.to_schema() for e in query.all())


def get_stored_exercise_meta(exercise: Exercise, lms_url: Optional[str] = None, ) -> Optional[dict]:
    """Returns the stored metadata associated with the exercise."""

    if lms_url is None:
        lms_url = get_lms_url()

    db_exercise_cls: Type[Exercise] = exercise.__class__.get_model_class()
    with get_db() as db:
        return db.query(db_exercise_cls.meta).filter_by(id=exercise.id,
                                                        lms_url=lms_url).scalar()  # type: ignore


def store_exercises(exercises: List[Exercise], lms_url: Optional[str] = None):
    """Stores the given exercises, all at once."""

    if lms_url is None:
        lms_url = get_lms_url()

    with get_db() as db:
        for e in exercises:
            exercise_model = e.to_model()
            exercise_model.lms_url = lms_url
            db.merge(exercise_model)
        db.commit()


def store_exercise(exercise: Exercise, lms_url: Optional[str] = None):
    """Stores the given exercise."""
    store_exercises([exercise], lms_url)
