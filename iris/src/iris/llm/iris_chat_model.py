"""The chat model handle the agent pipelines work with.

It wraps a request handler and keeps per-call state that the pipelines read
after a call: the usage of the latest call and the log-probabilities of the
latest text answer. It speaks Iris messages directly, without LangChain.
"""

import copy
from typing import Any, List, Optional, Sequence

from iris.common.pipeline_enum import PipelineEnum
from iris.common.pyris_message import PyrisMessage
from iris.common.token_logprob_dto import TokenLogprobEntry
from iris.common.token_usage_dto import TokenUsageDTO
from iris.domain.data.text_message_content_dto import TextMessageContentDTO
from iris.llm.completion_arguments import CompletionArguments
from iris.llm.errors import IncompleteModelResponse
from iris.llm.request_handler.request_handler_interface import RequestHandler
from iris.llm.structured_output import ModelT, parse_structured_output


def message_text(message: PyrisMessage) -> str:
    """The visible text of a model response."""
    return "".join(
        content.text_content
        for content in message.contents
        if isinstance(content, TextMessageContentDTO) and content.text_content
    )


class IrisChatModel:
    """A chat model bound to one configured model id and default arguments."""

    def __init__(
        self,
        request_handler: RequestHandler,
        completion_args: Optional[CompletionArguments] = None,
    ):
        self.request_handler = request_handler
        self.completion_args = completion_args or CompletionArguments()
        # Usage of the most recent call; replaced on every call (also a failed
        # one that reported usage), so callers can de-duplicate by identity.
        self.tokens: Optional[TokenUsageDTO] = None
        # Log-probabilities of the most recent call that produced text content.
        # A text answer always overwrites them, also with None, so a later
        # answer never inherits an earlier turn's values.
        self.last_token_logprobs: Optional[List[float]] = None
        self.last_token_logprob_entries: Optional[List[TokenLogprobEntry]] = None

    @property
    def model_name(self) -> str:
        return getattr(self.request_handler, "model_id", "unknown")

    def chat(
        self,
        messages: list[PyrisMessage],
        tools: Optional[Sequence[Any]] = None,
        tool_choice: Optional[str] = None,
    ) -> PyrisMessage:
        """Send the messages (and tool definitions) and return the response."""
        arguments = self.completion_args
        if tool_choice is not None:
            arguments = copy.copy(arguments)
            arguments.tool_choice = tool_choice
        try:
            response = self.request_handler.chat(messages, arguments, tools or None)
        except IncompleteModelResponse as error:
            if error.token_usage is not None:
                self._record_usage(error.token_usage)
            if arguments.stream_handler is not None:
                arguments.stream_handler(None)
            raise
        if message_text(response):
            self.last_token_logprobs = response.token_logprobs
            self.last_token_logprob_entries = response.token_logprob_entries
        self._record_usage(response.token_usage)
        return response

    def structured(self, messages: list[PyrisMessage], schema: type[ModelT]) -> ModelT:
        """Ask for an answer that follows ``schema`` and return it validated."""
        arguments = copy.copy(self.completion_args)
        arguments.response_schema = schema
        previous, self.completion_args = self.completion_args, arguments
        try:
            response = self.chat(messages)
        finally:
            self.completion_args = previous
        return parse_structured_output(schema, message_text(response))

    def _record_usage(self, usage: TokenUsageDTO) -> None:
        self.tokens = usage.model_copy(update={"pipeline": PipelineEnum.NOT_SET})
