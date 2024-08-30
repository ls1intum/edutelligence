from typing import Optional, List

from pydantic.fields import Field
from pydantic.main import BaseModel

from athena import GradingCriterion
from athena.text import Feedback, Submission, Exercise

############################################
#        What we send to the model         #
class EvaluationFeedback(Feedback):
    pass


class Assessment(BaseModel):
    id: str
    feedbacks: List[Feedback] = []
    meta: dict = {}


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


############################################
#    What we expect the model to return    #
class Metric(BaseModel):
    title: str
    summary: str
    description: str


class MetricEvaluation(BaseModel):
    title: str = Field(..., description="The title of the metric.")
    score: int = Field(..., ge=1, le=5, description="The score of the metric.")


class MetricEvaluations(BaseModel):
    evaluations: list[MetricEvaluation] = Field(..., description="The evaluations of the metrics.")


############################################
#       How we store the response          #
class Evaluation(BaseModel):
    response: dict = Field(..., description="The raw response from the model.")
    parsed_response: MetricEvaluations = Field(..., description="The parsed response from the model.")
    total_tokens: int = Field(..., description="The total number of tokens used.")
    prompt_tokens: int = Field(..., description="The number of tokens used in the prompt.")
    completion_tokens: int = Field(..., description="The number of tokens used in the completion.")
    cost: float = Field(..., description="The total cost of the model invocation.")


# re-export with shorter names, because the module will only use these
Exercise = EvaluationExercise
Submission = EvaluationSubmission
Feedback = EvaluationFeedback
