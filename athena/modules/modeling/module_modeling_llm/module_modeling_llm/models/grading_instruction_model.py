from typing import List
from pydantic import BaseModel, Field

class Criterion(BaseModel):
    description: str = Field(..., description="Description of the grading criterion")

class GradingItem(BaseModel):
    id: int = Field(..., description="ID of this grading item, cronological order")
    name: str = Field(..., description="Name of the grading item")
    points: float = Field(..., description="Points allocated to this grading item")
    criteria: List[Criterion] = Field(..., description="List of criteria for full credit")

class GradingInstructionModel(BaseModel):
    total_points: float = Field(..., description="Total points for the entire assessment")
    items: List[GradingItem] = Field(..., description="List of grading items")