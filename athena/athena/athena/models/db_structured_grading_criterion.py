from sqlalchemy import Column, JSON, String, ForeignKey
from sqlalchemy.orm import relationship

from athena.database import Base
from .big_integer_with_autoincrement import BigIntegerWithAutoincrement


class DBStructuredGradingCriterion(Base):
    __tablename__ = "structured_grading_criterion"
    id = Column(BigIntegerWithAutoincrement, primary_key=True, index=True,
                autoincrement=True)
    exercise_id = Column(BigIntegerWithAutoincrement, ForeignKey("exercises.id", ondelete="CASCADE"), index=True, unique=True) # Only one cached instruction per exercise
    instructions_hash = Column(String, nullable=False)
    structured_grading_criterion = Column(JSON, nullable=False)
    lms_url = Column(String, nullable=False)
    
    exercise = relationship("DBExercise", back_populates="structured_grading_criterion")