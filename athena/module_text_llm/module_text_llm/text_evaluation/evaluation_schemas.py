from typing import Optional, List, Dict

from athena import GradingCriterion
from athena.text import Feedback, Submission, Exercise


class EvaluationFeedback(Feedback):
    pass  # Inherits everything from TextFeedback


class EvaluationSubmission(Submission):
    feedbacks: Optional[Dict[str, List[EvaluationFeedback]]] = {}
    exercise_id: Optional[int] = None  # Allow exercise_id to be optional

    class Config:
        fields = {
            'exercise_id': 'exerciseId'  # Ensure the field name matches JSON key
        }


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
Feedback = EvaluationFeedback
