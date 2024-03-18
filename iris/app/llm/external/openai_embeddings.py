from typing import Literal, Any
from openai import OpenAI
from openai.lib.azure import AzureOpenAI

from ...llm.external.model import EmbeddingModel


class OpenAIEmbeddingModel(EmbeddingModel):
    model: str
    api_key: str
    _client: OpenAI

    def embed(self, text: str) -> list[float]:
        response = self._client.embeddings.create(
            model=self.model,
            input=text,
            encoding_format="float",
        )
        return response.data[0].embedding


class DirectOpenAIEmbeddingModel(OpenAIEmbeddingModel):
    type: Literal["openai_embedding"]

    def model_post_init(self, __context: Any) -> None:
        self._client = OpenAI(api_key=self.api_key)

    def __str__(self):
        return f"OpenAIEmbedding('{self.model}')"


class AzureOpenAIEmbeddingModel(OpenAIEmbeddingModel):
    type: Literal["azure_embedding"]
    endpoint: str
    azure_deployment: str
    api_version: str

    def model_post_init(self, __context: Any) -> None:
        self._client = AzureOpenAI(
            azure_endpoint=self.endpoint,
            azure_deployment=self.azure_deployment,
            api_version=self.api_version,
            api_key=self.api_key,
        )

    def __str__(self):
        return f"AzureEmbedding('{self.model}')"
