from typing import Union

from .cohere_client import CohereAzureClient
from ...llm.external.model import LanguageModel
from ...llm.external.openai_completion import (
    DirectOpenAICompletionModel,
    AzureOpenAICompletionModel,
)
from ...llm.external.openai_chat import DirectOpenAIChatModel, AzureOpenAIChatModel
from ...llm.external.openai_embeddings import (
    DirectOpenAIEmbeddingModel,
    AzureOpenAIEmbeddingModel,
)
from ...llm.external.ollama import OllamaModel

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
