from typing import Optional, List

from pydantic.main import BaseModel

from athena import GradingCriterion
from athena.text import Feedback, Submission, Exercise


class Assessment(BaseModel):
    id: str
    feedbacks: List[Feedback] = []


class EvaluationSubmission(Submission):
    assessments: List[Assessment] = []


class EvaluationExercise(Exercise):
    submissions: Optional[List[EvaluationSubmission]] = []
    grading_criteria: Optional[List[GradingCriterion]] = []

    def __init__(self, **data):
        super().__init__(**data)
        for submission in self.submissions:
            if submission.exercise_id is None:
                submission.exercise_id = self.id  # Manually set exercise_id for each submission

# re-export with shorter names, because the module will only use these
Exercise = EvaluationExercise
Submission = EvaluationSubmission
