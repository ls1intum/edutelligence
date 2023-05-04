from typing import List, Iterable, Optional

from .models import DBExercise
from athena.database import get_db
from athena.common.schemas import ExerciseType, Exercise
from athena.programming.schemas import Exercise as PExercise
from athena.text.schemas import Exercise as TExercise


def _exercise_type_to_model(exercise_type: ExerciseType) -> type:
    """Returns the database model class for this exercise type."""
    if exercise_type == ExerciseType.text:
        return TExercise
    elif exercise_type == ExerciseType.programming:
        return PExercise
    else:
        raise ValueError(f"Unknown exercise type: {exercise_type}")

def _exercise_model_to_schema(db_exercise: DBExercise) -> Exercise:
    """Converts a database model to a schema."""
    exercise_type = ExerciseType[db_exercise.type]
    model_class = DBExercise.model_from_exercise_type(exercise_type)
    return model_class(**db_exercise.dict())

def _exercise_schema_to_model(schema_exercise) -> DBExercise:
    """Converts a schema to a database model."""
    model_class = schema_exercise.get_model_class()
    return model_class(**schema_exercise.dict())

def get_stored_exercises(exercise_type: Optional[ExerciseType] = None, only_ids: Optional[List[int]] = None) -> Iterable[Exercise]:
    """
    Returns a list of exercises for the given exercise type and exercise ids.
    If type is None, returns all exercises.
    If only_ids is None, returns all exercises for the given exercise type.
    """
    with get_db() as db:
        query = db.query(DBExercise)
        if type is not None:
            query = query.filter_by(type=exercise_type.name)
        if only_ids is not None:
            query = query.filter(DBExercise.id.in_(only_ids))
        return (_exercise_model_to_schema(exercise_type, e) for e in query.all())

def store_exercises(exercises: List[Exercise]):
    """Stores the given exercises, all at once."""
    with get_db() as db:
        db_exercises = (_exercise_schema_to_model(e) for e in exercises)
        for e in db_exercises:
            db.merge(e)
        db.commit()

def store_exercise(exercise: Exercise):
    """Stores the given exercise."""
    store_exercises([exercise])
