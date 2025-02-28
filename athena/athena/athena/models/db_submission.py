from sqlalchemy import Column, JSON, String

from .model import Model
from .big_integer_with_autoincrement import BigIntegerWithAutoincrement


class DBSubmission(Model):
    id = Column(BigIntegerWithAutoincrement, primary_key=True, index=True, autoincrement=True,)
    lms_url = Column(String, index=True, nullable=False)
    meta = Column(JSON, nullable=False)
