from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship

from athena.database import Base
from .big_integer_with_autoincrement import BigIntegerWithAutoincrement


class DBStructuredGradingCriterion(Base):
    __tablename__ = "structured_grading_criterions"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    
    exercise_id = Column(BigIntegerWithAutoincrement, ForeignKey("text_exercises.id", ondelete="CASCADE"), index=True)

    exercise = relationship("DBTextExercise", back_populates="structured_grading_criterions")
    structured_grading_instructions = relationship("DBStructuredGradingInstruction", back_populates="structured_grading_criterion")
