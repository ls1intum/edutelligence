from typing import List, Optional, Sequence
from pydantic import BaseModel, Field

class FeedbackModel(BaseModel):
    title: str = Field(description="Very short title, i.e. feedback category or similar", example="Logic Error")
    description: str = Field(description="Feedback description")
    element_names: Optional[List[str]] = Field(description="Referenced diagram element names, and relations (R<number>) or empty if unreferenced")
    credits: float = Field(0.0, description="Number of points received/deducted")
    grading_instruction_id: int = Field(
        description="ID of the grading instruction that was used to generate this feedback"
    )

    class Config:
        title = "Feedback"

class AssessmentModel(BaseModel):
    """Collection of feedbacks making up an assessment"""

    feedbacks: Sequence[FeedbackModel] = Field(description="Assessment feedbacks, make sure to include all grading instructions")

    class Config:
        title = "Assessment"