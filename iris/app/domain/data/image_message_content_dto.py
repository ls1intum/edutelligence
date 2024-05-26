from pydantic import BaseModel, Field
from typing import Optional


class ImageMessageContentDTO(BaseModel):
    base64: str
    prompt: Optional[str]
