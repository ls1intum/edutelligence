from sqlalchemy import Column, String
from sqlalchemy.orm import relationship

from athena.database import Base
from .db_exercise import DBExercise


class DBTextExercise(DBExercise, Base):
    __tablename__ = "text_exercises"

    example_solution: str = Column(String)  # type: ignore

    structured_grading_criterions = relationship("DBStructuredGradingCriterion", back_populates="exercise")
    submissions = relationship("DBTextSubmission", back_populates="exercise")
    feedbacks = relationship("DBTextFeedback", back_populates="exercise")

