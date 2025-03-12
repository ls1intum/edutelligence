from typing import Union

from ...llm.external.model import LanguageModel
from ...llm.external.ollama import OllamaModel
from ...llm.external.openai_chat import AzureOpenAIChatModel, DirectOpenAIChatModel
from ...llm.external.openai_completion import (
    AzureOpenAICompletionModel,
    DirectOpenAICompletionModel,
)
from ...llm.external.openai_embeddings import (
    AzureOpenAIEmbeddingModel,
    DirectOpenAIEmbeddingModel,
)
from .cohere_client import CohereAzureClient

AnyLLM = Union[
    DirectOpenAICompletionModel,
    AzureOpenAICompletionModel,
    DirectOpenAIChatModel,
    AzureOpenAIChatModel,
    DirectOpenAIEmbeddingModel,
    AzureOpenAIEmbeddingModel,
    OllamaModel,
    CohereAzureClient,
]
