from sqlalchemy import Column, Integer, String, Float, JSON, Enum as SqlEnum

from athena.schemas import ExerciseType
from .model import Model


class DBExercise(Model):
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True)
    type = Column(SqlEnum(ExerciseType), index=True)
    max_points = Column(Float, index=True)
    bonus_points = Column(Float, index=True)
    problem_statement = Column(String)
    grading_instructions = Column(String)
    meta = Column(JSON)
