from typing import Optional, Sequence, Union, Dict, Any, Type, Callable

from langchain_core.tools import BaseTool
from pydantic import ConfigDict
from pydantic import BaseModel

from app.common.pyris_message import PyrisMessage
from app.domain.data.image_message_content_dto import ImageMessageContentDTO
from app.llm import LanguageModel
from app.llm.request_handler import RequestHandler
from app.llm.completion_arguments import CompletionArguments
from app.llm.llm_manager import LlmManager


class BasicRequestHandler(RequestHandler):
    model_id: str
    llm_manager: LlmManager | None = None
    model_config = ConfigDict(arbitrary_types_allowed=True)

    def __init__(self, model_id: str):
        super().__init__(model_id=model_id, llm_manager=None)
        self.model_id = model_id
        self.llm_manager = LlmManager()

    def complete(
        self,
        prompt: str,
        arguments: CompletionArguments,
        image: Optional[ImageMessageContentDTO] = None,
    ) -> str:
        llm = self.llm_manager.get_llm_by_id(self.model_id)
        return llm.complete(prompt, arguments, image)

    def chat(
        self,
        messages: list[PyrisMessage],
        arguments: CompletionArguments,
        tools: Optional[
            Sequence[Union[Dict[str, Any], Type[BaseModel], Callable, BaseTool]]
        ],
    ) -> PyrisMessage:
        llm = self.llm_manager.get_llm_by_id(self.model_id)
        return llm.chat(messages, arguments, tools)

    def embed(self, text: str) -> list[float]:
        llm = self.llm_manager.get_llm_by_id(self.model_id)
        return llm.embed(text)

    def bind_tools(
        self,
        tools: Sequence[Union[Dict[str, Any], Type[BaseModel], Callable, BaseTool]],
    ) -> LanguageModel:
        """
        Binds a sequence of tools to the language model.

        Args:
            tools (Sequence[Union[Dict[str, Any], Type[BaseModel], Callable, BaseTool]]):
            A sequence of tools to be bound.

        Returns:
            LanguageModel: The language model with tools bound.
        """
        llm = self.llm_manager.get_llm_by_id(self.model_id)
        llm.bind_tools(tools)
        return llm
