from sqlalchemy import Column, Integer, String, JSON, ForeignKey
from sqlalchemy.orm import relationship

from athena.storage.database import Base


class DBSubmission(Base):
    __tablename__ = "submissions"

    id = Column(Integer, primary_key=True, index=True)
    exercise_id = Column(Integer, ForeignKey("exercises.id", ondelete="CASCADE"), index=True)
    content = Column(String)
    student_id = Column(Integer, index=True)

    meta = Column(JSON)

    exercise = relationship("DBExercise", back_populates="submissions")
    feedbacks = relationship("DBFeedback", back_populates="submission")
