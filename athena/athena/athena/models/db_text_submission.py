from sqlalchemy import ForeignKey, Integer, Column
from sqlalchemy.orm import relationship

from . import DBSubmission
from athena.schemas import ExerciseType
from athena.database import Base


class DBTextSubmission(DBSubmission, Base):
    __tablename__ = "text_submissions"

    exercise_id = Column(Integer, ForeignKey("text_exercises.id", ondelete="CASCADE"), index=True)

    exercise = relationship("DBTextExercise", back_populates="submissions")
    feedbacks = relationship("DBTextFeedback", back_populates="submission")
