from abc import ABCMeta, abstractmethod
from pydantic import BaseModel

from domain import IrisMessage
from llm import CompletionArguments


class AbstractLlmWrapper(BaseModel, metaclass=ABCMeta):
    """Abstract class for the llm wrappers"""

    id: str
    name: str
    description: str


class AbstractLlmCompletionWrapper(AbstractLlmWrapper, metaclass=ABCMeta):
    """Abstract class for the llm completion wrappers"""

    @classmethod
    def __subclasshook__(cls, subclass):
        return hasattr(subclass, "completion") and callable(subclass.completion)

    @abstractmethod
    def completion(self, prompt: str, arguments: CompletionArguments) -> str:
        """Create a completion from the prompt"""
        raise NotImplementedError


class AbstractLlmChatCompletionWrapper(AbstractLlmWrapper, metaclass=ABCMeta):
    """Abstract class for the llm chat completion wrappers"""

    @classmethod
    def __subclasshook__(cls, subclass):
        return hasattr(subclass, "chat_completion") and callable(
            subclass.chat_completion
        )

    @abstractmethod
    def chat_completion(
        self, messages: list[any], arguments: CompletionArguments
    ) -> IrisMessage:
        """Create a completion from the chat messages"""
        raise NotImplementedError


class AbstractLlmEmbeddingWrapper(AbstractLlmWrapper, metaclass=ABCMeta):
    """Abstract class for the llm embedding wrappers"""

    @classmethod
    def __subclasshook__(cls, subclass):
        return hasattr(subclass, "create_embedding") and callable(
            subclass.create_embedding
        )

    @abstractmethod
    def create_embedding(self, text: str) -> list[float]:
        """Create an embedding from the text"""
        raise NotImplementedError
