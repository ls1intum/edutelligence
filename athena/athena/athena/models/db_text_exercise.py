from athena.schemas.exercise_type import ExerciseType
from sqlalchemy import Column, String, ForeignKey
from sqlalchemy.orm import relationship

from .db_exercise import DBExercise
from .big_integer_with_autoincrement import BigIntegerWithAutoincrement


class DBTextExercise(DBExercise):
    __tablename__ = "text_exercises"
    id = Column(BigIntegerWithAutoincrement, ForeignKey('exercise.id'), primary_key=True)

    example_solution: str = Column(String)  # type: ignore

    submissions = relationship("DBTextSubmission", back_populates="exercise")
    feedbacks = relationship("DBTextFeedback", back_populates="exercise")

    __mapper_args__ = {
        'polymorphic_identity': ExerciseType.text.value
    }