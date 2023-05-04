from sqlalchemy import Column, Integer, Boolean, String, Float, JSON, ForeignKey

from .model import Model


class DBFeedback(Model):
    __tablename__ = "feedbacks"

    id = Column(Integer, primary_key=True, index=True)
    exercise_id = Column(Integer, ForeignKey("exercises.id", ondelete="CASCADE"), index=True)
    submission_id = Column(Integer, ForeignKey("submissions.id", ondelete="CASCADE"), index=True)
    detail_text = Column(String)
    reference = Column(String, nullable=True)
    text = Column(String)
    credits = Column(Float)

    meta = Column(JSON)

    # not in the schema, but used in the database to distinguish between feedbacks and feedback suggestions
    is_suggestion = Column(Boolean, default=False)
