from typing import List, Optional, Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import (
    BaseChatModel,
)
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatResult
from langchain_core.outputs.chat_generation import ChatGeneration

from domain import IrisMessage, IrisMessageRole
from llm import RequestHandler, CompletionArguments


def convert_iris_message_to_base_message(iris_message: IrisMessage) -> BaseMessage:
    role_map = {
        IrisMessageRole.USER: "human",
        IrisMessageRole.ASSISTANT: "ai",
        IrisMessageRole.SYSTEM: "system",
    }
    return BaseMessage(content=iris_message.text, type=role_map[iris_message.role])


def convert_base_message_to_iris_message(base_message: BaseMessage) -> IrisMessage:
    role_map = {
        "human": IrisMessageRole.USER,
        "ai": IrisMessageRole.ASSISTANT,
        "system": IrisMessageRole.SYSTEM,
    }
    return IrisMessage(
        text=base_message.content, role=IrisMessageRole(role_map[base_message.type])
    )


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
        iris_messages = [convert_base_message_to_iris_message(m) for m in messages]
        iris_message = self.request_handler.chat(
            iris_messages, CompletionArguments(stop=stop)
        )
        base_message = convert_iris_message_to_base_message(iris_message)
        chat_generation = ChatGeneration(message=base_message)
        return ChatResult(generations=[chat_generation])

    @property
    def _llm_type(self) -> str:
        return "Iris"
