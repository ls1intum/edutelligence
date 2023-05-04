from sqlalchemy import Column, Integer, ForeignKey, String
from sqlalchemy.orm import relationship

from . import DBExercise
from athena.schemas import ExerciseType


class DBTextExercise(DBExercise):
    __mapper_args__ = {"polymorphic_identity": ExerciseType.text}

    example_solution = Column(String)

    # submissions = relationship("DBTextSubmission", back_populates="exercise")
    # feedbacks = relationship("DBTextFeedback", back_populates="exercise")
