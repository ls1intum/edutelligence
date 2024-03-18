from enum import Enum

from pydantic import BaseModel

from domain.iris_image import IrisImage


class IrisMessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class IrisMessage(BaseModel):
    text: str = ""
    role: IrisMessageRole
    images: list[IrisImage] = []

    def __str__(self):
        return f"{self.role.lower()}: {self.text}"
