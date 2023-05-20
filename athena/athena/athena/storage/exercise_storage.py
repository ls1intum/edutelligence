from typing import List, Iterable, Optional, Type

from athena.database import get_db
from athena.schemas import Exercise


def get_stored_exercises(exercise_cls: Type[Exercise], only_ids: Optional[List[int]] = None) -> Iterable[Exercise]:
    """
    Returns a list of exercises for the given exercise type and exercise ids.
    If only_ids is None, returns all exercises for the given exercise type.
    """
    db_exercise_cls = exercise_cls.get_model_class()
    with get_db() as db:
        query = db.query(db_exercise_cls)
        if only_ids is not None:
            query = query.filter(db_exercise_cls.id.in_(only_ids))
        return (e.to_schema() for e in query.all())


def get_stored_exercise_meta(exercise: Exercise) -> Optional[dict]:
    """Returns the stored metadata associated with the exercise."""
    db_exercise_cls = exercise.__class__.get_model_class()
    with get_db() as db:
        return db.query(db_exercise_cls.meta).filter_by(id=exercise.id).scalar()


def store_exercises(exercises: List[Exercise]):
    """Stores the given exercises, all at once."""
    with get_db() as db:
        for e in exercises:
            db.merge(e.to_model())
        db.commit()


def store_exercise(exercise: Exercise):
    """Stores the given exercise."""
    store_exercises([exercise])
