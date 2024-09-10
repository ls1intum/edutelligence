from sqlalchemy import Column, ForeignKey, JSON, String

from athena.database import Base
from .model import Model
from .big_integer_with_autoincrement import BigIntegerWithAutoincrement

class DBStructuredGradingInstruction(Model, Base):
    id = Column(BigIntegerWithAutoincrement, primary_key=True, index=True, autoincrement=True)
    exercise_id = Column(BigIntegerWithAutoincrement, ForeignKey("exercises.id", ondelete="CASCADE"), index=True)
    cache_key = Column(String, index=True, nullable=False)
    criteria = Column(JSON, nullable=False)