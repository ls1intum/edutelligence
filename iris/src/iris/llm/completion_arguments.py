from enum import Enum

CompletionArgumentsResponseFormat = Enum("TEXT", "JSON")


class CompletionArguments:
    """Arguments for the completion request"""

    def __init__(
        self,
        temperature: float = None,
        stop: list[str] = None,
        response_format: CompletionArgumentsResponseFormat = "TEXT",
    ):
        self.temperature = temperature
        self.stop = stop
        self.response_format = response_format
