from typing import Optional

from pydantic import BaseModel, Field


class ImageMessageContentDTO(BaseModel):
    image_data: Optional[str] = Field(alias="imageData", default=None)
