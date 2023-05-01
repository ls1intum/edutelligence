from sqlalchemy import Column, Integer, String, Float, JSON, Enum as SqlEnum, ForeignKey
from sqlalchemy.orm import relationship

from athena.schemas import ExerciseType
from athena.storage.database import Base


class DBExercise(Base):
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

    submissions = relationship("DBSubmission", back_populates="exercise")
    feedbacks = relationship("DBFeedback", back_populates="exercise")

class DBTextExercise(DBExercise):
    __tablename__ = "text_exercises"
    __mapper_args__ = {"polymorphic_identity": "text"}

    id = Column(Integer, ForeignKey("exercises.id"), primary_key=True)
    example_solution = Column(String)

class DBProgrammingExercise(DBExercise):
    __tablename__ = "programming_exercises"
    __mapper_args__ = {"polymorphic_identity": "programming"}

    id = Column(Integer, ForeignKey("exercises.id"), primary_key=True)
    programming_language = Column(String)
    solution_repository_url = Column(String)
    template_repository_url = Column(String)
    tests_repository_url = Column(String)