import logging
from typing import List, Optional, Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import (
    BaseChatModel,
)
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatResult, ChatGeneration

from app.common.PipelineEnum import PipelineEnum
from ...common import (
    convert_iris_message_to_langchain_message,
    convert_langchain_message_to_iris_message,
)
from app.common.token_usage_dto import TokenUsageDTO
from ...llm import RequestHandler, CompletionArguments


class IrisLangchainChatModel(BaseChatModel):
    """Custom langchain chat model for our own request handler"""

    request_handler: RequestHandler
    completion_args: CompletionArguments
    tokens: TokenUsageDTO = None
    logger = logging.getLogger(__name__)

    def __init__(
        self,
        request_handler: RequestHandler,
        completion_args: Optional[CompletionArguments] = CompletionArguments(stop=None),
        **kwargs: Any
    ) -> None:
        super().__init__(
            request_handler=request_handler, completion_args=completion_args, **kwargs
        )

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any
    ) -> ChatResult:
        iris_messages = [convert_langchain_message_to_iris_message(m) for m in messages]
        self.completion_args.stop = stop
        iris_message = self.request_handler.chat(iris_messages, self.completion_args)
        base_message = convert_iris_message_to_langchain_message(iris_message)
        chat_generation = ChatGeneration(message=base_message)
        self.tokens = TokenUsageDTO(
            model=iris_message.token_usage.model_info,
            numInputTokens=iris_message.token_usage.num_input_tokens,
            costPerMillionInputToken=iris_message.token_usage.cost_per_input_token,
            numOutputTokens=iris_message.token_usage.num_output_tokens,
            costPerMillionOutputToken=iris_message.token_usage.cost_per_output_token,
            pipeline=PipelineEnum.NOT_SET,
        )
        return ChatResult(generations=[chat_generation])

    @property
    def _llm_type(self) -> str:
        return "Iris"
