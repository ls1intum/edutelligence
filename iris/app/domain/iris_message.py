from enum import Enum

from pydantic import BaseModel
from .pyris_image import PyrisImage


class IrisMessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class IrisMessage(BaseModel):
    text: str = ""
    role: IrisMessageRole
    images: list[PyrisImage] | None

    def __init__(
        self, role: IrisMessageRole, text: str, images: list[PyrisImage] | None = None
    ):
        super().__init__(role=role, text=text)
        self.images = images

    def __str__(self):
        return f"{self.role.lower()}: {self.text}"
