from sqlalchemy import ForeignKey, Column, String
from sqlalchemy.orm import relationship

from athena.database import Base
from .db_submission import DBSubmission
from .big_integer_with_autoincrement import BigIntegerWithAutoincrement


class DBModellingSubmission(DBSubmission, Base):
    __tablename__ = "modelling_submissions"
    model: str = Column(String, nullable=False)  # type: ignore

    exercise_id = Column(BigIntegerWithAutoincrement, ForeignKey("modelling_exercises.id", ondelete="CASCADE"), index=True)

    exercise = relationship("DBModellingExercise", back_populates="submissions")
    feedbacks = relationship("DBModellingFeedback", back_populates="submission")
