from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class BuildLogEntryDTO(BaseModel):
    timestamp: Optional[datetime] = None
    message: Optional[str] = None

    def __str__(self):
        return f"{self.timestamp}: {self.message}"
