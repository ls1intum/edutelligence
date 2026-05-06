import queue
import threading
from logging import Logger
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence, Type, Union

from langchain_core.language_models import LanguageModelInput
from langchain_core.language_models.chat_models import (
    BaseChatModel,
)
from langchain_core.messages import AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatResult
from langchain_core.outputs.chat_generation import ChatGeneration, ChatGenerationChunk
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from iris.common.logging_config import get_logger
from iris.common.pipeline_enum import PipelineEnum
from iris.common.token_usage_dto import TokenUsageDTO

from ...common.message_converters import (
    convert_iris_message_to_langchain_message,
    convert_langchain_message_to_iris_message,
)
from ...llm import CompletionArguments, RequestHandler


class IrisLangchainChatModel(BaseChatModel):
    """Custom langchain chat model for our own request handler"""

    request_handler: RequestHandler
    completion_args: CompletionArguments
    tokens: TokenUsageDTO = None
    logger: Logger = get_logger(__name__)
    tools: Optional[
        Sequence[Union[Dict[str, Any], Type[BaseModel], Callable, BaseTool]]
    ] = Field(default_factory=list, alias="tools")

    def __init__(
        self,
        request_handler: RequestHandler,
        completion_args: Optional[CompletionArguments] = CompletionArguments(stop=None),
        **kwargs: Any,
    ) -> None:
        super().__init__(
            request_handler=request_handler,
            completion_args=completion_args,
            **kwargs,
        )

    def bind_tools(
        self,
        tools: Sequence[Union[Dict[str, Any], Type[BaseModel], Callable, BaseTool]],
        **_kwargs: Any,
    ) -> Runnable[LanguageModelInput, BaseMessage]:
        """Bind a sequence of tools to the request handler for function calling support.

        Args:
            tools: Sequence of tools that can be one of:
                  - Dict describing the tool
                  - Pydantic BaseModel
                  - Callable function
                  - BaseTool instance
            **kwargs: Additional arguments passed to the request handler

        Returns:
            self: Returns this instance as a Runnable

        Raises:
            ValueError: If tools sequence is empty or contains invalid tool types
        """
        if not tools:
            raise ValueError("At least one tool must be provided")

        self.tools = tools
        return self

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager=None,  # pylint: disable=unused-argument
        **_kwargs: Any,
    ) -> ChatResult:
        iris_messages = [convert_langchain_message_to_iris_message(m) for m in messages]
        self.completion_args.stop = stop
        iris_message = self.request_handler.chat(
            iris_messages, self.completion_args, self.tools
        )
        base_message = convert_iris_message_to_langchain_message(iris_message)
        chat_generation = ChatGeneration(message=base_message)
        self.tokens = TokenUsageDTO(
            model=iris_message.token_usage.model_info,
            numInputTokens=iris_message.token_usage.num_input_tokens,
            costPerMillionInputToken=iris_message.token_usage.cost_per_million_input_token,
            numOutputTokens=iris_message.token_usage.num_output_tokens,
            costPerMillionOutputToken=iris_message.token_usage.cost_per_million_output_token,
            pipeline=PipelineEnum.NOT_SET,
        )
        return ChatResult(generations=[chat_generation])

    def _stream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager=None,
        **_kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        """Stream tokens from the underlying model using a thread + queue bridge.

        The blocking HTTP call runs in a background thread. Tokens arrive via
        the on_token callback and are placed into a queue; this generator pulls
        from the queue and yields LangChain ChatGenerationChunks, which causes
        LangChain to fire on_llm_new_token callbacks on each chunk.

        For tool-call responses the model emits no content tokens, so no chunks
        would be yielded from the queue loop. LangChain requires at least one
        chunk from _stream(), so we yield the full response as a single synthetic
        chunk in that case.
        """
        iris_messages = [convert_langchain_message_to_iris_message(m) for m in messages]
        self.completion_args.stop = stop

        token_queue: queue.Queue[Optional[str]] = queue.Queue()
        error_holder: list[Exception] = []
        result_holder: list = []  # stores the final PyrisMessage for tool-call fallback

        def _run_chat() -> None:
            try:
                iris_message = self.request_handler.chat(
                    iris_messages,
                    self.completion_args,
                    self.tools,
                    on_token=token_queue.put,
                )
                result_holder.append(iris_message)
                self.tokens = TokenUsageDTO(
                    model=iris_message.token_usage.model_info,
                    numInputTokens=iris_message.token_usage.num_input_tokens,
                    costPerMillionInputToken=iris_message.token_usage.cost_per_million_input_token,
                    numOutputTokens=iris_message.token_usage.num_output_tokens,
                    costPerMillionOutputToken=iris_message.token_usage.cost_per_million_output_token,
                    pipeline=PipelineEnum.NOT_SET,
                )
            except Exception as exc:  # pylint: disable=broad-except
                error_holder.append(exc)
            finally:
                token_queue.put(None)  # sentinel: signal completion

        thread = threading.Thread(target=_run_chat, daemon=True)
        thread.start()

        chunks_yielded = 0
        while True:
            token = token_queue.get()
            if token is None:
                break
            chunk = ChatGenerationChunk(message=AIMessageChunk(content=token))
            if run_manager:
                run_manager.on_llm_new_token(token, chunk=chunk)
            yield chunk
            chunks_yielded += 1

        thread.join()

        if error_holder:
            raise error_holder[0]

        # Tool-call responses produce no content tokens, so the loop above yields
        # nothing. LangChain's stream() raises ValueError if _stream() is empty,
        # so we emit one chunk carrying the full tool-call structure.
        if chunks_yielded == 0 and result_holder:
            base_message = convert_iris_message_to_langchain_message(result_holder[0])
            chunk_msg = AIMessageChunk(
                content=base_message.content or "",
                additional_kwargs=base_message.additional_kwargs,
                tool_calls=getattr(base_message, "tool_calls", []),
            )
            yield ChatGenerationChunk(message=chunk_msg)

    @property
    def _llm_type(self) -> str:
        return "Iris"

    @property
    def model_name(self) -> str:
        """Return the underlying model name for Langfuse tracing."""
        if hasattr(self.request_handler, "model_id"):
            return self.request_handler.model_id
        return "unknown"

    @property
    def model(self) -> str:
        """Alias for model_name - some integrations look for this."""
        return self.model_name

    @property
    def _identifying_params(self) -> Dict[str, Any]:
        """Return identifying parameters for LangChain/Langfuse."""
        return {"model_name": self.model_name, "model": self.model_name}
