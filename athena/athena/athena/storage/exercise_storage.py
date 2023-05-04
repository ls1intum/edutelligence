from typing import List, Iterable, Union

from .database import get_db
from .models.exercise import DBExercise, DBTextExercise, DBProgrammingExercise
from athena.common.schemas import Exercise, ExerciseType


def _exercise_from_db_model(db_exercise) -> Exercise:
    if db_exercise.type == ExerciseType.text:
        return TextExercise.from_orm(db_exercise)
    elif db_exercise.type == ExerciseType.programming:
        return ProgrammingExercise.from_orm(db_exercise)
    else:
        raise ValueError(f"Unknown exercise type: {db_exercise.type}")

def get_stored_exercises(type: Union[Exercise, None] = None, only_ids: Union[List[int], None] = None) -> Iterable[Exercise]:
    """
    Returns a list of exercises for the given exercise type and exercise ids.
    If type is None, returns all exercises.
    If only_ids is None, returns all exercises for the given exercise type.
    """
    with get_db() as db:
        query = db.query(DBExercise)
        if type is not None:
            query = query.filter_by(type=type)
        if only_ids is not None:
            query = query.filter(DBExercise.id.in_(only_ids))
        return (_exercise_from_db_model(e) for e in query.all())

def store_exercises(exercises: List[Exercise]):
    """Stores the given exercises, all at once."""
    with get_db() as db:
        db_exercises = []
        for e in exercises:
            if isinstance(e, TextExercise):
                db_exercises.append(DBTextExercise(**e.dict()))
            elif isinstance(e, ProgrammingExercise):
                db_exercises.append(DBProgrammingExercise(**e.dict()))
            else:
                raise ValueError(f"Unknown exercise type: {type(e)}")
        for e in db_exercises:
            db.merge(e)
        db.commit()

def store_exercise(exercise: Exercise):
    """Stores the given exercise."""
    store_exercises([exercise])
