from sqlalchemy import Column, Integer, String, Float, JSON
from sqlalchemy.orm import relationship

from ..database import Base


class DBExercise(Base):
    __tablename__ = "exercises"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True)
    type = Column(String, index=True)
    max_points = Column(Float, index=True)
    problem_statement = Column(String)
    example_solution = Column(String)
    student_id = Column(Integer, index=True)
    meta = Column(JSON)

    submissions = relationship("DBSubmission", back_populates="exercise")
    feedbacks = relationship("DBFeedback", back_populates="exercise")
