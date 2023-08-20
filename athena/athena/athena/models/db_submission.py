from sqlalchemy import Column, JSON

from .model import Model
from .big_integer_with_autoincrement import BigIntegerWithAutoincrement


class DBSubmission(Model):
    id = Column(BigIntegerWithAutoincrement, primary_key=True, index=True, autoincrement=True,)
    meta = Column(JSON, nullable=False)
