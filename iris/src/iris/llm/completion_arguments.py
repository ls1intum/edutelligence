from enum import Enum
from typing import Optional

from openai.types.shared import ReasoningEffort

CompletionArgumentsResponseFormat = Enum("TEXT", "JSON")


class CompletionArguments:
    """Arguments for the completion request"""

    def __init__(
        self,
        temperature: float = None,
        max_tokens: int = None,
        stop: list[str] = None,
        response_format: CompletionArgumentsResponseFormat = "TEXT",
        reasoning_effort: Optional[ReasoningEffort] = None,
    ):
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.stop = stop
        self.response_format = response_format
        self.reasoning_effort = reasoning_effort
