from sqlalchemy import Column, Integer, Boolean, String, Float, JSON

from .model import Model


class DBFeedback(Model):
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    detail_text = Column(String, nullable=False)
    text = Column(String, nullable=False)
    credits = Column(Float, nullable=False)
    meta = Column(JSON, nullable=False)

    # not in the schema, but used in the database to distinguish between feedbacks and feedback suggestions
    is_suggestion = Column(Boolean, default=False, nullable=False)
