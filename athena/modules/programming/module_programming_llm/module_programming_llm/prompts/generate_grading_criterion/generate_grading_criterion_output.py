from pydantic import BaseModel, Field

from athena import StructuredGradingCriterion


class GenerateGradingCriterionOutput(BaseModel):
    """Collection of structured grading criterion for a problem"""
    structured_grading_criterion: StructuredGradingCriterion = Field(description="Structured grading criterion")
