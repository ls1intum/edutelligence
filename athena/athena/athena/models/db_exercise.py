from sqlalchemy import Column, Integer, String, Float, JSON, Enum as SqlEnum, ForeignKey

from athena.schemas import ExerciseType
from .model import Model
from athena.database import Base


class DBExercise(Model, Base):
    __tablename__ = "exercises"
    __mapper_args__ = {
        "polymorphic_identity": "exercise",
        "polymorphic_on": "type",
    }

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True)
    type = Column(SqlEnum(ExerciseType), index=True)
    max_points = Column(Float, index=True)
    bonus_points = Column(Float, index=True)
    problem_statement = Column(String)
    grading_instructions = Column(String)
    meta = Column(JSON)

    # submission_id = Column(Integer, ForeignKey("submissions.id"), index=True)
    # feedback_id = Column(Integer, ForeignKey("feedbacks.id"), index=True)
