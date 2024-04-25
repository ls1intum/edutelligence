from pydantic import BaseModel
from typing import Optional


class PyrisImage(BaseModel):
    base64: str
    prompt: Optional[str] = None
    mime_type: Optional[str] = "jpeg"

    class Config:
        json_schema_extra = {
            "example": {
                "prompt": "Example prompt",
                "base64": "base64EncodedString==",
                "mime_type": "jpeg",
            }
        }
