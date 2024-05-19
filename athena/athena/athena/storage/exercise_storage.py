from typing import List, Iterable, Optional, Type

from athena.contextvars import get_artemis_url
from athena.database import get_db
from athena.schemas import Exercise


def get_stored_exercises(exercise_cls: Type[Exercise], artemis_url: str = None, only_ids: Optional[List[int]] = None) -> \
Iterable[Exercise]:
    """
    Returns a list of exercises for the given exercise type and exercise ids.
    If only_ids is None, returns all exercises for the given exercise type.
    """

    if artemis_url is None:
        artemis_url = get_artemis_url()

    db_exercise_cls = exercise_cls.get_model_class()
    with get_db() as db:
        query = db.query(db_exercise_cls)
        if only_ids is not None:
            query = query.filter(db_exercise_cls.id.in_(only_ids))  # type: ignore
        query = query.filter(db_exercise_cls.artemis_url == artemis_url)  # type: ignore
        return (e.to_schema() for e in query.all())


def get_stored_exercise_meta(exercise: Exercise, artemis_url: str = None, ) -> Optional[dict]:
    """Returns the stored metadata associated with the exercise."""

    if artemis_url is None:
        artemis_url = get_artemis_url()

    db_exercise_cls: Type[Exercise] = exercise.__class__.get_model_class()
    with get_db() as db:
        return db.query(db_exercise_cls.meta).filter_by(id=exercise.id,
                                                        artemis_url=artemis_url).scalar()  # type: ignore


def store_exercises(exercises: List[Exercise], artemis_url: str = None):
    """Stores the given exercises, all at once."""

    if artemis_url is None:
        artemis_url = get_artemis_url()

    with get_db() as db:
        for e in exercises:
            exercise_model = e.to_model()
            exercise_model.artemis_url = artemis_url
            db.merge(exercise_model)
        db.commit()


def store_exercise(exercise: Exercise, artemis_url: str = None):
    """Stores the given exercise."""
    store_exercises([exercise], artemis_url)
