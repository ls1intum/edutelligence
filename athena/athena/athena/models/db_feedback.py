from sqlalchemy import Column, Integer, Boolean, String, Float, JSON, UniqueConstraint

from .model import Model


class DBFeedback(Model):
    __table_args__ = (UniqueConstraint('lms_id'),)

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    lms_id = Column(Integer)
    title = Column(String)
    description = Column(String)
    credits = Column(Float, nullable=False)
    grading_instruction_id = Column(Integer)
    meta = Column(JSON, nullable=False)

    # not in the schema, but used in the database to distinguish between feedbacks and feedback suggestions
    is_suggestion = Column(Boolean, default=False, nullable=False)
