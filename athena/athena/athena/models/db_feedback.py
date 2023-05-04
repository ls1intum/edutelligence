from sqlalchemy import Column, Integer, Boolean, String, Float, JSON

from .model import Model


class DBFeedback(Model):
    id = Column(Integer, primary_key=True, index=True)
    detail_text = Column(String)
    reference = Column(String, nullable=True)
    text = Column(String)
    credits = Column(Float)
    meta = Column(JSON)

    # not in the schema, but used in the database to distinguish between feedbacks and feedback suggestions
    is_suggestion = Column(Boolean, default=False)
