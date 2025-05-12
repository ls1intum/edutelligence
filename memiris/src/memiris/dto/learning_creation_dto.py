from pydantic import BaseModel, Field


class LearningCreationDto(BaseModel):

    title: str = Field(description="The title of the learning object. Should be short.")
    content: str = Field(
        description="The content of the learning object. "
        "Contains the information that was learned and details about it."
    )
