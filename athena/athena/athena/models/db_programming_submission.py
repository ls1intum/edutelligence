from sqlalchemy.orm import relationship

from . import DBSubmission
from athena.schemas import ExerciseType


class DBProgrammingSubmission(DBSubmission):
    __mapper_args__ = {"polymorphic_identity": ExerciseType.programming}

    exercise = relationship("DBProgrammingExercise", back_populates="submissions")
    feedbacks = relationship("DBProgrammingFeedback", back_populates="submission")