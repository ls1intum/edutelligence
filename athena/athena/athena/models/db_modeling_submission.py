from sqlalchemy import ForeignKey, Column, String
from sqlalchemy.orm import relationship

from athena.database import Base
from .db_submission import DBSubmission
from .big_integer_with_autoincrement import BigIntegerWithAutoincrement


class DBModelingSubmission(DBSubmission, Base):
    __tablename__ = "modeling_submissions"
    model: str = Column(String, nullable=False)  # type: ignore

    exercise_id = Column(BigIntegerWithAutoincrement, ForeignKey("modeling_exercises.id", ondelete="CASCADE"), index=True)

    exercise = relationship("DBModelingExercise", back_populates="submissions")
    feedbacks = relationship("DBModelingFeedback", back_populates="submission")
