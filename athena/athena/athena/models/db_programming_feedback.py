from sqlalchemy import Column, Integer, ForeignKey
from sqlalchemy.orm import relationship

from . import DBFeedback
from athena.schemas import ExerciseType
from athena.database import Base


class DBProgrammingFeedback(DBFeedback, Base):
    __tablename__ = "programming_feedbacks"

    exercise_id = Column(Integer, ForeignKey("programming_exercises.id", ondelete="CASCADE"), index=True)
    submission_id = Column(Integer, ForeignKey("programming_submissions.id", ondelete="CASCADE"), index=True)

    exercise = relationship("DBProgrammingExercise", back_populates="feedbacks")
    submission = relationship("DBProgrammingSubmission", back_populates="feedbacks")
