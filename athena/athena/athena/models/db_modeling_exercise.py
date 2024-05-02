from sqlalchemy import Column, String
from sqlalchemy.orm import relationship

from athena.database import Base
from .db_exercise import DBExercise


class DBModelingExercise(DBExercise, Base):
    __tablename__ = "modeling_exercises"

    example_solution: str = Column(String)  # type: ignore

    submissions = relationship("DBModelingSubmission", back_populates="exercise")
    feedbacks = relationship("DBModelingFeedback", back_populates="exercise")
