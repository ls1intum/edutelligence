from abc import ABCMeta, abstractmethod
from typing import Any, Callable, Dict, Optional, Sequence, Type, Union

from langchain_core.tools import BaseTool
from openai.types.chat import ChatCompletionMessage
from pydantic import BaseModel

from ...common.pyris_message import PyrisMessage
from ...llm import CompletionArguments


class LanguageModel(BaseModel, metaclass=ABCMeta):
    """Abstract class for the llm wrappers"""

    id: str
    model: str


class CompletionModel(LanguageModel, metaclass=ABCMeta):
    """Abstract class for the llm completion wrappers"""

    @classmethod
    def __subclasshook__(cls, subclass) -> bool:
        return hasattr(subclass, "complete") and callable(subclass.complete)

    @abstractmethod
    def complete(self, prompt: str, arguments: CompletionArguments) -> str:
        """Create a completion from the prompt"""
        raise NotImplementedError(f"The LLM {str(self)} does not support completion")


class ChatModel(LanguageModel, metaclass=ABCMeta):
    """Abstract class for the llm chat completion wrappers"""

    cost_per_million_input_token: float = 0
    cost_per_million_output_token: float = 0

    @classmethod
    def __subclasshook__(cls, subclass) -> bool:
        return hasattr(subclass, "chat") and callable(subclass.chat)

    @abstractmethod
    def chat(
        self,
        messages: list[PyrisMessage],
        arguments: CompletionArguments,
        tools: Optional[
            Sequence[Union[Dict[str, Any], Type[BaseModel], Callable, BaseTool]]
        ],
    ) -> ChatCompletionMessage:
        """Create a completion from the chat messages"""
        raise NotImplementedError(
            f"The LLM {str(self)} does not support chat completion"
        )


class EmbeddingModel(LanguageModel, metaclass=ABCMeta):
    """Abstract class for the llm embedding wrappers"""

    cost_per_million_input_token: float = 0

    @classmethod
    def __subclasshook__(cls, subclass) -> bool:
        return hasattr(subclass, "embed") and callable(subclass.embed)

    @abstractmethod
    def embed(self, text: str) -> list[float]:
        """Create an embedding from the text"""
        raise NotImplementedError(f"The LLM {str(self)} does not support embeddings")


class ImageGenerationModel(LanguageModel, metaclass=ABCMeta):
    """Abstract class for the llm image generation wrappers"""

    @classmethod
    def __subclasshook__(cls, subclass):
        return hasattr(subclass, "generate_images") and callable(
            subclass.generate_images
        )

    @abstractmethod
    def generate_images(
        self,
        prompt: str,
        n: int = 1,
        size: str = "256x256",
        quality: str = "standard",
        **kwargs,
    ) -> list:
        """Create an image from the prompt"""
        raise NotImplementedError(
            f"The LLM {str(self)} does not support image generation"
        )
