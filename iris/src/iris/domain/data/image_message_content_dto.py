from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class ImageMessageContentDTO(BaseModel):
    base64: str = Field(..., alias="pdfFile")
    prompt: Optional[str] = None
    model_config = ConfigDict(populate_by_name=True)
