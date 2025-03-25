from pydantic import BaseModel, model_validator
from typing import Dict, List


class Score(BaseModel):
    feedback_type: str
    value: float

class Metric(BaseModel):
    metric_id: str
    scores: List[Score]

class Submission(BaseModel):
    submission_id: str
    metrics: List[Metric]

class Exercise(BaseModel):
    exercise_id: str
    submissions: List[Submission]

class Evaluation(BaseModel):
    exercises: List[Exercise]
    has_started_evaluating: bool
    is_finished_evaluating: bool
    current_submission_index: int
    current_exercise_index: int

    @staticmethod
    def _convert_scores(feedbacks: Dict[str, float]) -> List[Score]:
        """Convert feedback dict to Score objects"""
        return [Score(feedback_type=fb_type, value=score)
                for fb_type, score in feedbacks.items()]

    @staticmethod
    def _convert_metrics(metrics: Dict[str, Dict[str, float]]) -> List[Metric]:
        """Convert metrics dict to Metric objects"""
        return [Metric(metric_id=metric_id, scores=Evaluation._convert_scores(feedbacks))
                for metric_id, feedbacks in metrics.items()]

    @staticmethod
    def _convert_submissions(submissions: Dict[str, Dict[str, Dict[str, float]]]) -> List[Submission]:
        """Convert submissions dict to Submission objects"""
        return [Submission(submission_id=sub_id, metrics=Evaluation._convert_metrics(metrics))
                for sub_id, metrics in submissions.items()]

    @staticmethod
    def _convert_exercises(exercises: Dict[str, Dict]) -> List[Exercise]:
        """Convert exercises dict to Exercise objects"""
        return [Exercise(exercise_id=ex_id, submissions=Evaluation._convert_submissions(submissions))
                for ex_id, submissions in exercises.items()]

    @model_validator(mode="before")
    @classmethod
    def transform_structure(cls, data: Dict) -> Dict:
        """Converts nested dict structure into typed Pydantic model"""
        if "selected_values" in data and isinstance(data["selected_values"], dict):
            data["exercises"] = cls._convert_exercises(data["selected_values"])
            del data["selected_values"]
        return data
