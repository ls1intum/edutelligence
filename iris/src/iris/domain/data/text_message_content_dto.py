from pydantic import BaseModel, ConfigDict, Field


class TextMessageContentDTO(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    text_content: str = Field(alias="textContent", default="")
