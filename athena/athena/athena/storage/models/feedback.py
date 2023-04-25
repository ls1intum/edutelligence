from sqlalchemy import Column, Integer, String, Float, JSON, ForeignKey
from sqlalchemy.orm import relationship

from ..database import Base


class DBFeedback(Base):
    __tablename__ = "feedbacks"

    id = Column(Integer, primary_key=True, index=True)
    exercise_id = Column(Integer, ForeignKey("exercises.id"), index=True)
    submission_id = Column(Integer, ForeignKey("submissions.id"), index=True)
    detail_text = Column(String)
    text = Column(String)
    credits = Column(Float)
    meta = Column(JSON)

    # not in the schema, but used in the database to distinguish between feedbacks and feedback suggestions
    is_suggestion = Column(Integer, default=0)

    exercise = relationship("DBExercise", back_populates="feedbacks")
    submission = relationship("DBSubmission", back_populates="feedbacks")
