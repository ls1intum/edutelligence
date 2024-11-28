from typing import Optional

from sqlalchemy import Column, ForeignKey, String
from sqlalchemy.orm import relationship

from athena.database import Base
from .db_feedback import DBFeedback
from .big_integer_with_autoincrement import BigIntegerWithAutoincrement


class DBModelingFeedback(DBFeedback, Base):
    __tablename__ = "modeling_feedbacks"

    element_ids: Optional[list[str]] = Column(JSON) # type: ignore
    reference: Optional[str] = Column(String, nullable=True) # type: ignore

    exercise_id = Column(BigIntegerWithAutoincrement, ForeignKey("modeling_exercises.id", ondelete="CASCADE"), index=True)
    submission_id = Column(BigIntegerWithAutoincrement, ForeignKey("modeling_submissions.id", ondelete="CASCADE"), index=True)

    exercise = relationship("DBModelingExercise", back_populates="feedbacks")
    submission = relationship("DBModelingSubmission", back_populates="feedbacks")
