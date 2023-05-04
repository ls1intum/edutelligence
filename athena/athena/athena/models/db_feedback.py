from sqlalchemy import Column, Integer, Boolean, String, Float, JSON, ForeignKey

from .model import Model
from athena.database import Base


class DBFeedback(Model, Base):
    __tablename__ = "feedbacks"

    id = Column(Integer, primary_key=True, index=True)
    detail_text = Column(String)
    reference = Column(String, nullable=True)
    text = Column(String)
    credits = Column(Float)
    meta = Column(JSON)

    exercise_id = Column(Integer, ForeignKey("exercises.id", ondelete="CASCADE"), index=True)
    submission_id = Column(Integer, ForeignKey("submissions.id", ondelete="CASCADE"), index=True)

    # not in the schema, but used in the database to distinguish between feedbacks and feedback suggestions
    is_suggestion = Column(Boolean, default=False)
