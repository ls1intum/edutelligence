class CompletionArguments:
    """Arguments for the completion request"""

    def __init__(
        self, max_tokens: int = None, temperature: float = None, stop: list[str] = None
    ):
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.stop = stop
