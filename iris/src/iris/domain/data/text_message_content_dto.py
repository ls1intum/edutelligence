from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class TextMessageContentDTO(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    type: Literal["text"] = "text"
    text_content: str = Field(alias="textContent", default="")
