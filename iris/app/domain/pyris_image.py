from datetime import datetime
from typing import Any  # Import Any for type hinting


class PyrisImage:
    def __init__(
        self,
        prompt: str,
        base64: str,
        timestamp: datetime,
        mime_type: str = "jpeg",
        raw_data: Any = None,
    ):
        self.prompt = prompt
        self.type = mime_type
        self.base64 = base64
        self.timestamp = timestamp
        self._raw_data = raw_data
