from typing import Literal, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class ImageMessageContentDTO(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    type: Literal["image"] = "image"
    base64: str = Field(
        ...,
        validation_alias=AliasChoices("imageData", "pdfFile"),
        serialization_alias="imageData",
    )
    prompt: Optional[str] = None
