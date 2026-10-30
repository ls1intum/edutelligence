"""Errors raised by the model clients."""

from typing import Optional

from iris.common.token_usage_dto import TokenUsageDTO


class IncompleteModelResponse(RuntimeError):
    """The provider stopped before the response was complete.

    Raised instead of returning a response whose tool calls or output items may
    be truncated. Carries the usage of the call so it can still be billed.
    """

    def __init__(self, message: str, token_usage: Optional[TokenUsageDTO] = None):
        super().__init__(message)
        self.token_usage = token_usage
