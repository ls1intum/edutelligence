from pydantic import BaseModel
from datetime import datetime


class PyrisImage(BaseModel):
    prompt: str
    base64: str
    timestamp: datetime
    mime_type: str = "jpeg"

    class Config:
        schema_extra = {
            "example": {
                "prompt": "Example prompt",
                "base64": "base64EncodedString==",
                "timestamp": "2023-01-01T12:00:00Z",
                "mime_type": "jpeg",
            }
        }
