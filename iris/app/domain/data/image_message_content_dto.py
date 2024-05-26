from pydantic import BaseModel
from typing import Optional


class ImageMessageContentDTO(BaseModel):
    base64: str
    prompt: Optional[str]
