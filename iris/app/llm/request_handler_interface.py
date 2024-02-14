from abc import ABCMeta, abstractmethod

from domain import IrisMessage
from llm.generation_arguments import CompletionArguments


class RequestHandlerInterface(metaclass=ABCMeta):
    """Interface for the request handlers"""

    @classmethod
    def __subclasshook__(cls, subclass):
        return (
            hasattr(subclass, "completion")
            and callable(subclass.completion)
            and hasattr(subclass, "chat_completion")
            and callable(subclass.chat_completion)
            and hasattr(subclass, "create_embedding")
            and callable(subclass.create_embedding)
        )

    @abstractmethod
    def completion(self, prompt: str, arguments: CompletionArguments) -> str:
        """Create a completion from the prompt"""
        raise NotImplementedError

    @abstractmethod
    def chat_completion(
        self, messages: list[any], arguments: CompletionArguments
    ) -> IrisMessage:
        """Create a completion from the chat messages"""
        raise NotImplementedError

    @abstractmethod
    def create_embedding(self, text: str) -> list[float]:
        """Create an embedding from the text"""
        raise NotImplementedError
