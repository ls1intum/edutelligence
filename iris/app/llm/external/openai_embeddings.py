import logging
from typing import Literal, Any
from openai import (
    OpenAI,
    APIError,
    APITimeoutError,
    RateLimitError,
    InternalServerError,
)
from openai.lib.azure import AzureOpenAI

from ...llm.external.model import EmbeddingModel
import time


class OpenAIEmbeddingModel(EmbeddingModel):
    model: str
    api_key: str
    _client: OpenAI

    def embed(self, text: str) -> list[float]:
        retries = 5
        backoff_factor = 2
        initial_delay = 1
        # Maximum wait time: 1 + 2 + 4 + 8 + 16 = 31 seconds

        for attempt in range(retries):
            try:
                response = self._client.embeddings.create(
                    model=self.model,
                    input=text,
                    encoding_format="float",
                )
                return response.data[0].embedding
            except (
                APIError,
                APITimeoutError,
                RateLimitError,
                InternalServerError,
            ):
                wait_time = initial_delay * (backoff_factor**attempt)
                logging.exception(f"OpenAI error on attempt {attempt + 1}")
                logging.info(f"Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
        raise Exception(f"Failed to get embedding from OpenAI after {retries} retries.")


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
