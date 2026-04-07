from typing import Optional, Sequence
from pydantic import ConfigDict, BaseModel, Field

class FeedbackModel(BaseModel):
    title: str = Field(description="Very short title, i.e. feedback category or similar", examples=["Logic Error"])
    description: str = Field(description="Feedback description")
    element_name: Optional[str] = Field(None, description="Referenced diagram element, attribute names, and relations (use format: <ClassName>, <ClassName>.<AttributeName>, <ClassName>.<MethodName>, R<number>), or leave empty if unreferenced")
    credits: float = Field(0.0, description="Number of points received/deducted")
    grading_instruction_id: int = Field(
        description="ID of the grading instruction that was used to generate this feedback"
    )
    model_config = ConfigDict(title="Feedback")

class AssessmentModel(BaseModel):
    """Collection of feedbacks making up an assessment"""

    feedbacks: Sequence[FeedbackModel] = Field(description="Assessment feedbacks, make sure to include all grading instructions")
    model_config = ConfigDict(title="Assessment")