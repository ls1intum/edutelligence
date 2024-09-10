from sqlalchemy import Column, String, JSON
from athena.database import Base
from athena.models.model import Model
from athena.models.big_integer_with_autoincrement import BigIntegerWithAutoincrement

class DBGradingInstructionCache(Model, Base):
    __tablename__ = "grading_instruction_cache"

    id = Column(BigIntegerWithAutoincrement, primary_key=True, index=True, nullable=False)
    exercise_id = Column(BigIntegerWithAutoincrement, index=True, nullable=False)
    cache_key = Column(String, unique=True, index=True, nullable=False)
    grading_instructions = Column(JSON, nullable=False)