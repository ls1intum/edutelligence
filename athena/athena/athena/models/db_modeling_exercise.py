from athena.schemas.exercise_type import ExerciseType
from sqlalchemy import Column, String, ForeignKey
from sqlalchemy.orm import relationship
from .db_exercise import DBExercise
from .big_integer_with_autoincrement import BigIntegerWithAutoincrement
class DBModelingExercise(DBExercise):
    __tablename__ = "modeling_exercises"

    example_solution = Column(String)  # type: ignore
    
    id = Column(BigIntegerWithAutoincrement, ForeignKey('exercise.id'), primary_key=True)
    submissions = relationship("DBModelingSubmission", back_populates="exercise")
    feedbacks = relationship("DBModelingFeedback", back_populates="exercise")

    __mapper_args__ = {
        'polymorphic_identity': ExerciseType.modeling.value
    }