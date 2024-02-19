from enum import Enum

from pydantic import BaseModel


class IrisMessageRole(Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class IrisMessage(BaseModel):
    role: IrisMessageRole
    text: str

    def __init__(self, role: IrisMessageRole, text: str):
        super().__init__(role=role, text=text)

    def __str__(self):
        return f"IrisMessage(role={self.role.value}, text='{self.text}')"
