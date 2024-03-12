from enum import Enum

from pydantic import BaseModel


class IrisMessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class IrisMessage(BaseModel):
    text: str = ""
    role: IrisMessageRole

    def __str__(self):
        return f"{self.role.lower()}: {self.text}"
