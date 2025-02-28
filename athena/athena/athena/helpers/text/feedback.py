from typing import List, cast

from athena.database import get_db
from athena.models import DBTextFeedback
from athena.text import Feedback


def get_exercise_feedbacks(exercise_id: int) -> List[Feedback]:
    """
    Get all feedback on a given exercise.
    """
    with get_db() as db:
        return [
            cast(Feedback, f.to_schema())
            for f in db.query(DBTextFeedback).filter_by(exercise_id=exercise_id).all()
        ]