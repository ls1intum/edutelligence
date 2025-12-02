from enum import Enum
from typing import Optional


class CompletionArgumentsResponseFormat(str, Enum):
    TEXT = "TEXT"
    JSON = "JSON"


class CompletionArguments:
    """Arguments for the completion request"""

    def __init__(
        self,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        stop: Optional[list[str]] = None,
        response_format: CompletionArgumentsResponseFormat = CompletionArgumentsResponseFormat.TEXT,
    ):
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.stop = stop
        self.response_format = response_format
