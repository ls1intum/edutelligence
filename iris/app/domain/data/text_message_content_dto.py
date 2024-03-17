from typing import Optional

from pydantic import BaseModel, Field


class TextMessageContentDTO(BaseModel):
    text_content: Optional[str] = Field(alias="textContent", default=None)
