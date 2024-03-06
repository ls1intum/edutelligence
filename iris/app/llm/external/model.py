from abc import ABCMeta, abstractmethod
from pydantic import BaseModel

from domain import IrisMessage, PyrisImage
from llm import CompletionArguments
from llm.capability import CapabilityList


class LanguageModel(BaseModel, metaclass=ABCMeta):
    """Abstract class for the llm wrappers"""

    id: str
    name: str
    description: str
    capabilities: CapabilityList


class CompletionModel(LanguageModel, metaclass=ABCMeta):
    """Abstract class for the llm completion wrappers"""

    @classmethod
    def __subclasshook__(cls, subclass) -> bool:
        return hasattr(subclass, "complete") and callable(subclass.complete)

    @abstractmethod
    def complete(
        self, prompt: str, arguments: CompletionArguments, images: [PyrisImage] = None
    ) -> str:
        """Create a completion from the prompt"""
        raise NotImplementedError(
            f"The LLM {self.__str__()} does not support completion"
        )


class ChatModel(LanguageModel, metaclass=ABCMeta):
    """Abstract class for the llm chat completion wrappers"""

    @classmethod
    def __subclasshook__(cls, subclass) -> bool:
        return hasattr(subclass, "chat") and callable(subclass.chat)

    @abstractmethod
    def chat(
        self, messages: list[IrisMessage], arguments: CompletionArguments
    ) -> IrisMessage:
        """Create a completion from the chat messages"""
        raise NotImplementedError(
            f"The LLM {self.__str__()} does not support chat completion"
        )


class EmbeddingModel(LanguageModel, metaclass=ABCMeta):
    """Abstract class for the llm embedding wrappers"""

    @classmethod
    def __subclasshook__(cls, subclass) -> bool:
        return hasattr(subclass, "embed") and callable(subclass.embed)

    @abstractmethod
    def embed(self, text: str) -> list[float]:
        """Create an embedding from the text"""
        raise NotImplementedError(
            f"The LLM {self.__str__()} does not support embeddings"
        )


class ImageGenerationModel(LanguageModel, metaclass=ABCMeta):
    """Abstract class for the llm image generation wrappers"""

    @classmethod
    def __subclasshook__(cls, subclass):
        return hasattr(subclass, "generate_images") and callable(
            subclass.generate_images
        )

    @abstractmethod
    def generate_images(self, prompt: str, n: int, **kwargs) -> list[PyrisImage]:
        """Generate images from the prompt"""
        raise NotImplementedError
