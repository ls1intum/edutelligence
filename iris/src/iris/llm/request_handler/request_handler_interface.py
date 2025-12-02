from abc import ABCMeta, abstractmethod
from typing import Any, Callable, Dict, Optional, Sequence, Type, Union

from langchain_core.tools import BaseTool
from pydantic import BaseModel

from ...common.pyris_message import PyrisMessage
from ...domain.data.image_message_content_dto import ImageMessageContentDTO
from ...llm import CompletionArguments
from ..external.model import LanguageModel


class RequestHandler(BaseModel, metaclass=ABCMeta):
    """Interface for the request handlers"""

    @classmethod
    def __subclasshook__(cls, subclass) -> bool:
        return (
            hasattr(subclass, "complete")
            and callable(subclass.complete)
            and hasattr(subclass, "chat")
            and callable(subclass.chat)
            and hasattr(subclass, "embed")
            and callable(subclass.embed)
        )

    @abstractmethod
    def complete(
        self,
        prompt: str,
        arguments: CompletionArguments,
        image: Optional[ImageMessageContentDTO] = None,
    ) -> str:
        """Create a completion from the prompt"""
        raise NotImplementedError

    @abstractmethod
    def chat(
        self,
        messages: list[Any],
        arguments: CompletionArguments,
        tools: Optional[
            Sequence[Union[Dict[str, Any], Type[BaseModel], Callable, BaseTool]]
        ],
    ) -> PyrisMessage:
        """Create a completion from the chat messages"""
        raise NotImplementedError

    @abstractmethod
    def embed(self, text: str) -> list[float]:
        """Create an embedding from the text"""
        raise NotImplementedError

    @abstractmethod
    def bind_tools(
        self,
        tools: Sequence[Union[Dict[str, Any], Type[BaseModel], Callable, BaseTool]],
    ) -> LanguageModel:
        """Bind tools"""
        raise NotImplementedError
