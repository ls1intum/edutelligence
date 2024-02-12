from llm.wrapper.abstract_llm_wrapper import AbstractLlmWrapper
from llm.wrapper.open_ai_completion_wrapper import (
    OpenAICompletionWrapper,
    AzureCompletionWrapper,
)
from llm.wrapper.open_ai_chat_wrapper import (
    OpenAIChatCompletionWrapper,
    AzureChatCompletionWrapper,
)
from llm.wrapper.open_ai_embedding_wrapper import (
    OpenAIEmbeddingWrapper,
    AzureEmbeddingWrapper,
)
from llm.wrapper.ollama_wrapper import OllamaWrapper

type LlmWrapper = (
    OpenAICompletionWrapper
    | AzureCompletionWrapper
    | OpenAIChatCompletionWrapper
    | AzureChatCompletionWrapper
    | OpenAIEmbeddingWrapper
    | AzureEmbeddingWrapper
    | OllamaWrapper
)
