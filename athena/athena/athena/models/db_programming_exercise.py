from athena.schemas.exercise_type import ExerciseType
from sqlalchemy import Column, String, ForeignKey
from sqlalchemy.orm import relationship

from .db_exercise import DBExercise
from .big_integer_with_autoincrement import BigIntegerWithAutoincrement


class DBProgrammingExercise(DBExercise):
    __tablename__ = "programming_exercises"

    id = Column(BigIntegerWithAutoincrement, ForeignKey('exercise.id'), primary_key=True)
    programming_language: str = Column(String, nullable=False)  # type: ignore
    solution_repository_uri: str = Column(String, nullable=False) # type: ignore
    template_repository_uri: str = Column(String, nullable=False) # type: ignore
    tests_repository_uri: str = Column(String, nullable=False)  # type: ignore

    submissions = relationship("DBProgrammingSubmission", back_populates="exercise")
    feedbacks = relationship("DBProgrammingFeedback", back_populates="exercise")

    __mapper_args__ = {
        'polymorphic_identity': ExerciseType.programming.value
    }