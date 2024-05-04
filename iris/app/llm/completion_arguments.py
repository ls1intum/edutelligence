from enum import Enum

CompletionArgumentsResponseFormat = Enum("TEXT", "JSON")


class CompletionArguments:
    """Arguments for the completion request"""

    def __init__(
        self,
        max_tokens: int = None,
        temperature: float = None,
        stop: list[str] = None,
        response_format: CompletionArgumentsResponseFormat = "TEXT",
    ):
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.stop = stop
        self.response_format = response_format
