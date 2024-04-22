from enum import Enum
from pydantic import BaseModel
from typing import List, Optional
from .pyris_image import PyrisImage

class IrisMessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"

class IrisMessage(BaseModel):
    text: str = ""
    role: IrisMessageRole
    images: Optional[List[PyrisImage]] = None

    def __str__(self):
        return f"{self.role.lower()}: {self.text}"
