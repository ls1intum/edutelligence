from openai import OpenAI
from openai.lib.azure import AzureOpenAI

from llm.wrapper import (
    AbstractLlmEmbeddingWrapper,
)


class BaseOpenAIEmbeddingWrapper(AbstractLlmEmbeddingWrapper):

    def __init__(self, client, model: str, **kwargs):
        super().__init__(**kwargs)
        self.client = client
        self.model = model

    def create_embedding(self, text: str) -> list[float]:
        response = self.client.embeddings.create(
            model=self.model,
            input=text,
            encoding_format="float",
        )
        return response.data[0].embedding


class OpenAIEmbeddingWrapper(BaseOpenAIEmbeddingWrapper):

    def __init__(self, model: str, api_key: str, **kwargs):
        client = OpenAI(api_key=api_key)
        model = model
        super().__init__(client, model, **kwargs)

    def __str__(self):
        return f"OpenAIEmbedding('{self.model}')"


class AzureEmbeddingWrapper(BaseOpenAIEmbeddingWrapper):

    def __init__(
        self,
        model: str,
        endpoint: str,
        azure_deployment: str,
        api_version: str,
        api_key: str,
        **kwargs,
    ):
        client = AzureOpenAI(
            azure_endpoint=endpoint,
            azure_deployment=azure_deployment,
            api_version=api_version,
            api_key=api_key,
        )
        model = model
        super().__init__(client, model, **kwargs)

    def __str__(self):
        return f"AzureEmbedding('{self.model}')"
