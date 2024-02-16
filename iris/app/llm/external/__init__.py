from llm.external.model import LanguageModel
from llm.external.openai_completion import (
    DirectOpenAICompletionModel,
    AzureOpenAICompletionModel,
)
from llm.external.openai_chat import DirectOpenAIChatModel, AzureOpenAIChatModel
from llm.external.openai_embeddings import (
    DirectOpenAIEmbeddingModel,
    AzureOpenAIEmbeddingModel,
)
from llm.external.ollama import OllamaModel

type AnyLLM = (
    DirectOpenAICompletionModel
    | AzureOpenAICompletionModel
    | DirectOpenAIChatModel
    | AzureOpenAIChatModel
    | DirectOpenAIEmbeddingModel
    | AzureOpenAIEmbeddingModel
    | OllamaModel
)
