from enum import Enum

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
    """

    def __init__(
        self,
        temperature: float = None,
        max_tokens: int = None,
        stop: list[str] = None,
        response_format: CompletionArgumentsResponseFormat = "TEXT",
        reasoning_effort: ReasoningEffort = None,
        logprobs: bool = False,
    ):
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.stop = stop
        self.response_format = response_format
        self.reasoning_effort = reasoning_effort
        self.logprobs = logprobs
