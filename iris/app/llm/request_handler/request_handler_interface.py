from abc import ABCMeta, abstractmethod

from ...domain import PyrisMessage
from ...llm import CompletionArguments


class RequestHandler(metaclass=ABCMeta):
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
    def complete(self, prompt: str, arguments: CompletionArguments) -> str:
        """Create a completion from the prompt"""
        raise NotImplementedError

    @abstractmethod
    def chat(self, messages: list[any], arguments: CompletionArguments) -> PyrisMessage:
        """Create a completion from the chat messages"""
        raise NotImplementedError

    @abstractmethod
    def embed(self, text: str) -> list[float]:
        """Create an embedding from the text"""
        raise NotImplementedError
