from sqlalchemy import ForeignKey, Integer, Column
from sqlalchemy.orm import relationship

from athena.database import Base
from . import DBSubmission


class DBProgrammingSubmission(DBSubmission, Base):
    __tablename__ = "programming_submissions"

    exercise_id = Column(Integer, ForeignKey("programming_exercises.id", ondelete="CASCADE"), index=True)

    exercise = relationship("DBProgrammingExercise", back_populates="submissions")
    feedbacks = relationship("DBProgrammingFeedback", back_populates="submission")
