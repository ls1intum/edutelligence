from sqlalchemy import ForeignKey, Column, String
from sqlalchemy.orm import relationship

from athena.database import Base
from .db_submission import DBSubmission
from .big_integer_with_autoincrement import BigIntegerWithAutoincrement


class DBProgrammingSubmission(DBSubmission, Base):
    __tablename__ = "programming_submissions"
    repository_url: str = Column(String, nullable=False)  # type: ignore

    exercise_id = Column(BigIntegerWithAutoincrement, ForeignKey("programming_exercises.id", ondelete="CASCADE"), index=True)

    exercise = relationship("DBProgrammingExercise", back_populates="submissions")
    feedbacks = relationship("DBProgrammingFeedback", back_populates="submission")
