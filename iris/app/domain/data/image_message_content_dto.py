from pydantic import BaseModel, Field
from typing import Optional


class ImageMessageContentDTO(BaseModel):
    base64: str = Field(..., alias="base64")
    prompt: Optional[str]
