from sqlalchemy.orm import relationship

from . import DBFeedback
from athena.schemas import ExerciseType


class DBProgrammingFeedback(DBFeedback):
    __mapper_args__ = {"polymorphic_identity": ExerciseType.programming}

    # exercise = relationship("DBProgrammingExercise", back_populates="feedbacks")
    # submission = relationship("DBProgrammingSubmission", back_populates="feedbacks")
