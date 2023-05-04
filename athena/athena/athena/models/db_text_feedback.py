from sqlalchemy.orm import relationship

from . import DBFeedback
from athena.schemas import ExerciseType


class DBTextFeedback(DBFeedback):
    __mapper_args__ = {"polymorphic_identity": ExerciseType.text}

    # exercise = relationship("DBTextExercise", back_populates="feedbacks")
    # submission = relationship("DBTextSubmission", back_populates="feedbacks")