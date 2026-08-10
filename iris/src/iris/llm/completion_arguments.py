from enum import Enum
from typing import Callable, Optional

from openai.types.shared import ReasoningEffort

CompletionArgumentsResponseFormat = Enum("TEXT", "JSON")


class CompletionArguments:
    """Arguments for the completion request.

    ``reasoning_effort`` is only forwarded to the API when the underlying
    chat model declares ``supports_reasoning_effort: true`` in its YAML
    configuration. Models that do not declare support silently drop the
    value (with a debug log), so pipelines can request a reasoning effort
    unconditionally without breaking on models that do not support it.

    ``logprobs`` follows the same pattern: it is only forwarded to the API
    when the underlying chat model declares ``supports_logprobs: true``.
    When forwarded, the per-token log-probabilities are surfaced on the
    returned message so callers can derive a confidence score from them.

    ``top_logprobs`` requests the top-k alternative candidates per token
    (clamped to the OpenAI maximum of 20). It is only forwarded alongside
    ``logprobs``; there is no separate capability flag — backends that
    ignore it simply return plain logprobs, and confidence scoring falls
    back from the uncertainty method to the mean-logprob method.
    """

    def __init__(
        self,
        temperature: float = None,
        max_tokens: int = None,
        stop: list[str] = None,
        response_format: CompletionArgumentsResponseFormat = "TEXT",
        reasoning_effort: ReasoningEffort = None,
        logprobs: bool = False,
        top_logprobs: int = None,
        stream_handler: Optional[Callable[[Optional[str]], None]] = None,
    ):
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.stop = stop
        self.response_format = response_format
        self.reasoning_effort = reasoning_effort
        self.logprobs = logprobs
        self.top_logprobs = top_logprobs
        self.stream_handler = stream_handler
