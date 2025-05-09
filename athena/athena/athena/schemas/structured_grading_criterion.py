from typing import List
from athena.schemas.grading_criterion import GradingCriterion
from pydantic import BaseModel


class StructuredGradingCriterion(BaseModel):
    criteria: List[GradingCriterion]