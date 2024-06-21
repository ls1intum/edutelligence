from pydantic import BaseModel, Field, ConfigDict
from typing import Optional


class ImageMessageContentDTO(BaseModel):
    base64: str = Field(..., alias="pdfFile")
    prompt: Optional[str] = None
    model_config = ConfigDict(populate_by_name=True)
