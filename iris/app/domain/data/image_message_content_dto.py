from pydantic import BaseModel, Field
from typing import List, Optional


class ImageMessageContentDTO(BaseModel):
    base64: List[str] = Field(..., alias="base64")  # List of base64-encoded strings
    prompt: Optional[str] = Field(default=None, alias="prompt")

    class Config:
        json_schema_extra = {
            "example": {
                "prompt": "Example prompt",
                "base64": ["base64EncodedString==", "anotherBase64EncodedString=="],
            }
        }
