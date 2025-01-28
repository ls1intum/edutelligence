from sqlalchemy import Column, String, Float, JSON, Enum as SqlEnum
from sqlalchemy.orm import relationship
from athena.database import Base
from athena.schemas import ExerciseType
from .model import Model
from .big_integer_with_autoincrement import BigIntegerWithAutoincrement


class DBExercise(Model, Base):
    __tablename__ = "exercise"
    id = Column(BigIntegerWithAutoincrement, primary_key=True, index=True, nullable=False)
    lms_url = Column(String, index=True, nullable=False)
    title = Column(String, index=True, nullable=False)
    max_points = Column(Float, index=True, nullable=False)
    bonus_points = Column(Float, index=True, nullable=False)
    grading_instructions = Column(String)
    problem_statement = Column(String)
    grading_criteria = Column(JSON, nullable=True)
    meta = Column(JSON, nullable=False)

    # Polymorphism, discriminator attribute
    type = Column(SqlEnum(ExerciseType), index=True, nullable=False)

    __mapper_args__ = {
        'polymorphic_identity': 'exercise',
        'polymorphic_on': 'type'
    }