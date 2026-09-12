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
    # Whether the model exposes token-level log-probabilities. When True, a
    # pipeline can request them via CompletionArguments.logprobs and derive a
    # confidence score from the returned values. Defaults to False so models
    # that do not support logprobs (e.g. Ollama) are never asked for them.
    supports_logprobs: bool = False
    # Whether the model additionally accepts the `top_logprobs` parameter
    # (top-k alternative candidates per token, feeding the uncertainty
    # confidence method). Separate from `supports_logprobs` because strict
    # OpenAI-compatible backends reject unknown parameters with a 4xx rather
    # than ignoring them — set this False for such backends so requests keep
    # plain logprobs and confidence falls back to the mean-logprob strategy.
    supports_top_logprobs: bool = False

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


class RerankItem(BaseModel):
    """One scored document, identified by its index into the ``documents`` list
    that was passed to :meth:`RerankModel.rerank`."""

    index: int
    relevance_score: float


class RerankResponse(BaseModel):
    """Provider-neutral rerank result.

    Every reranker normalises its provider's response to this shape, so the
    model configured behind a reranker role can be swapped (Cohere <-> a
    vLLM-served cross-encoder) without touching any call site.
    """

    results: list[RerankItem]


class RerankModel(LanguageModel, metaclass=ABCMeta):
    """Abstract class for the llm reranker wrappers"""

    cost_per_1k_requests: float = 0

    @classmethod
    def __subclasshook__(cls, subclass) -> bool:
        return hasattr(subclass, "rerank") and callable(subclass.rerank)

    @abstractmethod
    def rerank(self, query: str, documents: list[str], top_n: int) -> RerankResponse:
        """Score the documents against the query"""
        raise NotImplementedError(f"The LLM {str(self)} does not support reranking")


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
