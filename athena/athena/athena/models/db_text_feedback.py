from typing import Optional

from sqlalchemy import Column, Integer, ForeignKey
from sqlalchemy.orm import relationship

from athena.database import Base
from .db_feedback import DBFeedback


class DBTextFeedback(DBFeedback, Base):
    __tablename__ = "text_feedbacks"

    index_start: Optional[int] = Column(Integer)  # type: ignore
    index_end: Optional[int] = Column(Integer)  # type: ignore

    exercise_id = Column(Integer, ForeignKey("text_exercises.id", ondelete="CASCADE"), index=True)
    submission_id = Column(Integer, ForeignKey("text_submissions.id", ondelete="CASCADE"), index=True)

    exercise = relationship("DBTextExercise", back_populates="feedbacks")
    submission = relationship("DBTextSubmission", back_populates="feedbacks")
