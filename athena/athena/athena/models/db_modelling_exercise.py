from sqlalchemy import Column, String
from sqlalchemy.orm import relationship

from athena.database import Base
from .db_exercise import DBExercise


class DBModellingExercise(DBExercise, Base):
    __tablename__ = "modelling_exercises"

    example_solution: str = Column(String)  # type: ignore

    submissions = relationship("DBModellingSubmission", back_populates="exercise")
    feedbacks = relationship("DBModellingFeedback", back_populates="exercise")
