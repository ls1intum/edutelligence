from typing import Optional, Sequence

from pydantic import BaseModel, Field


class FeedbackModel(BaseModel):
    title: str = Field(
        description="Very short title, i.e. feedback category", example="Logic Error"
    )
    description: str = Field(description="Feedback description")
    line_start: Optional[int] = Field(
        description="Referenced line number start, or empty if unreferenced"
    )
    line_end: Optional[int] = Field(
        description="Referenced line number end, or empty if unreferenced"
    )
    credits: float = Field(0.0, description="Number of points received/deducted")
    grading_instruction_id: Optional[int] = Field(
        description="ID of the grading instruction that was used to generate this feedback, or empty if no grading instruction was used"
    )
    file_name: str = Field(description="The name of the file")

    class Config:
        title = "Feedback"


class GenerateSuggestionsByFileOutput(BaseModel):
    """Collection of feedbacks making up an assessment for a file"""

    feedbacks: Sequence[FeedbackModel] = Field(description="Assessment feedbacks", default=[])

    class Config:
        title = "FileAssessment"