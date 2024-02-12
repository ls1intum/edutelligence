from enum import Enum


class IrisMessageRole(Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class IrisMessage:
    role: IrisMessageRole
    text: str

    def __init__(self, role: IrisMessageRole, text: str):
        self.role = role
        self.text = text

    def __str__(self):
        return f"IrisMessage(role={self.role.value}, text='{self.text}')"
