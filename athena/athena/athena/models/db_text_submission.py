from sqlalchemy.orm import relationship

from . import DBSubmission
from athena.schemas import ExerciseType


class DBTextSubmission(DBSubmission):
    __mapper_args__ = {"polymorphic_identity": ExerciseType.text}

    # exercise = relationship("DBTextExercise", back_populates="submissions")
    # feedbacks = relationship("DBTextFeedback", back_populates="submission")
