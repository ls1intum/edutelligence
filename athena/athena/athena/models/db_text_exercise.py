from sqlalchemy import Column, Integer, ForeignKey, String
from sqlalchemy.orm import relationship

from . import DBExercise
from athena.schemas import ExerciseType
from athena.database import Base


class DBTextExercise(DBExercise, Base):
    __tablename__ = "text_exercises"

    example_solution = Column(String)

    submissions = relationship("DBTextSubmission", back_populates="exercise")
    feedbacks = relationship("DBTextFeedback", back_populates="exercise")
