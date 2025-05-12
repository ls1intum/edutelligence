from uuid import UUID

from pydantic import BaseModel, Field


class LearningDto(BaseModel):

    id: UUID = Field(description="The unique identifier of the learning object.")
    title: str = Field(description="The title of the learning object. Should be short.")
    content: str = Field(
        description="The content of the learning object. "
        "Contains the information that was learned and details about it."
    )
