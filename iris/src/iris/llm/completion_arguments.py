import threading
from enum import Enum
from typing import Callable, Optional

from openai.types.shared import ReasoningEffort

CompletionArgumentsResponseFormat = Enum("TEXT", "JSON")

# Emergency output limit for pipelines with a short, prompt-defined output
# (titles, query rewrites, summaries, search answers). The prompt and schema
# control the length; this only stops a runaway generation. It is far above any
# normal answer, so a reasoning model does not run out of tokens while it
# reasons, and it stays below 16,384, the smallest output cap of the OpenAI
# models in llm_config.example.yml (gpt-4o-mini), which reject larger values.
EMERGENCY_MAX_TOKENS = 16_000


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

    ``tool_choice`` (for example ``"none"``) is forwarded by the OpenAI client
    when tools are sent.
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
        tool_choice: Optional[str] = None,
        cancel_event: Optional[threading.Event] = None,
        response_schema: Optional[type] = None,
    ):
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.stop = stop
        self.response_format = response_format
        self.reasoning_effort = reasoning_effort
        self.logprobs = logprobs
        self.top_logprobs = top_logprobs
        self.stream_handler = stream_handler
        # Sent only with tools, and only by the OpenAI client. "none" keeps the
        # tool list (and so the cached prompt prefix) but forbids tool calls.
        self.tool_choice = tool_choice
        # Set when the run is cancelled; retry waits wake up and stop early.
        self.cancel_event = cancel_event
        # A Pydantic model the answer must follow (see iris.llm.structured_output).
        # Takes precedence over response_format.
        self.response_schema = response_schema
