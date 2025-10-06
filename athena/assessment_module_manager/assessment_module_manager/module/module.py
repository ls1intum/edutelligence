from pydantic import BaseModel, Field, AnyHttpUrl

from athena import ExerciseType


class Module(BaseModel):
    """An Athena module, with the URL to the API as well as the type of module."""
    name: str = Field(examples=["module_example"])
    url: AnyHttpUrl = Field(examples=["http://localhost:5001"])
    type: ExerciseType = Field(examples=[ExerciseType.text])
    supports_evaluation: bool = Field(description="Whether the module supports evaluation", examples=[True])
    supports_non_graded_feedback_requests: bool = Field(description="Whether the module supports non-graded feedback requests", examples=[True])
    supports_graded_feedback_requests: bool = Field(description="Whether the module supports graded feedback requests", examples=[True])
