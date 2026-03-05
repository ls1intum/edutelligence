from typing import Union

from ...llm.external.ollama import OllamaModel
from ...llm.external.openai_chat import (
    AzureOpenAIChatModel,
    DirectOpenAIChatModel,
)
from ...llm.external.openai_completion import (
    AzureOpenAICompletionModel,
    DirectOpenAICompletionModel,
)
from ...llm.external.openai_embeddings import (
    AzureOpenAIEmbeddingModel,
    DirectOpenAIEmbeddingModel,
)
from ...llm.external.whisper import AzureWhisperModel, OpenAIWhisperModel
from .cohere_client import CohereAzureClient

AnyLlm = Union[
    DirectOpenAICompletionModel,
    AzureOpenAICompletionModel,
    DirectOpenAIChatModel,
    AzureOpenAIChatModel,
    DirectOpenAIEmbeddingModel,
    AzureOpenAIEmbeddingModel,
    OllamaModel,
    CohereAzureClient,
    AzureWhisperModel,
    OpenAIWhisperModel,
]
