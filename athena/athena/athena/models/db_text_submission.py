from sqlalchemy import ForeignKey, Integer, Column, String
from sqlalchemy.orm import relationship

from athena.database import Base
from .db_submission import DBSubmission


class DBTextSubmission(DBSubmission, Base):
    __tablename__ = "text_submissions"
    content: str = Column(String, nullable=False)  # type: ignore

    exercise_id = Column(Integer, ForeignKey("text_exercises.id", ondelete="CASCADE"), index=True)

    exercise = relationship("DBTextExercise", back_populates="submissions")
    feedbacks = relationship("DBTextFeedback", back_populates="submission")
