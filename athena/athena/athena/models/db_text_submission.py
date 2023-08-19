from sqlalchemy import ForeignKey, Column, String
from sqlalchemy.orm import relationship

from athena.database import Base
from .db_submission import DBSubmission
from .big_integer_with_autoincrement import BigIntegerWithAutoincrement


class DBTextSubmission(DBSubmission, Base):
    __tablename__ = "text_submissions"
    text: str = Column(String, nullable=False)  # type: ignore
    language: str = Column(String, nullable=True)  # type: ignore

    exercise_id = Column(BigIntegerWithAutoincrement, ForeignKey("text_exercises.id", ondelete="CASCADE"), index=True)

    exercise = relationship("DBTextExercise", back_populates="submissions")
    feedbacks = relationship("DBTextFeedback", back_populates="submission")
