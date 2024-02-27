from typing import List, Optional, Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import (
    BaseChatModel,
)
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatResult
from langchain_core.outputs.chat_generation import ChatGeneration

from common import (
    convert_iris_message_to_langchain_message,
    convert_langchain_message_to_iris_message,
)
from llm import RequestHandler, CompletionArguments


class IrisLangchainChatModel(BaseChatModel):
    """Custom langchain chat model for our own request handler"""

    request_handler: RequestHandler

    def __init__(self, request_handler: RequestHandler, **kwargs: Any) -> None:
        super().__init__(request_handler=request_handler, **kwargs)

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any
    ) -> ChatResult:
        iris_messages = [convert_langchain_message_to_iris_message(m) for m in messages]
        iris_message = self.request_handler.chat(
            iris_messages, CompletionArguments(stop=stop)
        )
        base_message = convert_iris_message_to_langchain_message(iris_message)
        chat_generation = ChatGeneration(message=base_message)
        return ChatResult(generations=[chat_generation])

    @property
    def _llm_type(self) -> str:
        return "Iris"
