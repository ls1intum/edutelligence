from sqlalchemy import Column, BigInteger, Boolean, String, Float, JSON, UniqueConstraint

from .model import Model
from .big_integer_with_autoincrement import BigIntegerWithAutoincrement


class DBFeedback(Model):
    __table_args__ = (UniqueConstraint('lms_id'),)

    id = Column(BigIntegerWithAutoincrement, primary_key=True, index=True, autoincrement=True)
    lms_id = Column(BigInteger)
    title = Column(String)
    description = Column(String)
    credits = Column(Float, nullable=False)
    structured_grading_instruction_id = Column(BigInteger)
    is_graded = Column(Boolean, nullable=True)
    meta = Column(JSON, nullable=False)

    # not in the schema, but used in the database to distinguish between feedbacks and feedback suggestions
    is_suggestion = Column(Boolean, default=False, nullable=False)
