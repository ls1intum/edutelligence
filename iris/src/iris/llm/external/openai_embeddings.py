import logging
import time
from typing import Literal

from langchain_experimental.text_splitter import SemanticChunker
from langchain_openai import AzureOpenAIEmbeddings, OpenAIEmbeddings
from openai import (
    APIError,
    APITimeoutError,
    InternalServerError,
    RateLimitError,
)

from iris.tracing import observe

from ...llm.external.model import EmbeddingModel


class OpenAIEmbeddingModel(EmbeddingModel):
    """OpenAIEmbeddingModel provides methods to generate text embeddings using the OpenAI API.

    It implements retry logic to handle API errors and supports semantic text splitting.
    """

    api_key: str
    _client: OpenAIEmbeddings

    @observe(name="OpenAI Embedding", as_type="embedding")
    def embed(self, text: str) -> list[float]:
        retries = 5
        backoff_factor = 2
        initial_delay = 1
        # Maximum wait time: 1 + 2 + 4 + 8 + 16 = 31 seconds

        for attempt in range(retries):
            try:
                return self._client.embed_query(text)
            except (
                APIError,
                APITimeoutError,
                RateLimitError,
                InternalServerError,
            ):
                wait_time = initial_delay * (backoff_factor**attempt)
                logging.exception("OpenAI error on attempt %s", attempt + 1)
                logging.info("Retrying in %s seconds...", wait_time)
                time.sleep(wait_time)
        raise RuntimeError(
            f"Failed to get embedding from OpenAI after {retries} retries."
        )

    def split_text_semantically(
        self,
        text: str,
        breakpoint_threshold_type: Literal[
            "percentile", "standard_deviation", "interquartile", "gradient"
        ] = "gradient",
        breakpoint_threshold_amount: float = 95.0,
        min_chunk_size: int = 512,
    ):
        chunker = SemanticChunker(
            self._client,
            breakpoint_threshold_type=breakpoint_threshold_type,
            breakpoint_threshold_amount=breakpoint_threshold_amount,
            min_chunk_size=min_chunk_size,
        )

        return chunker.split_text(text)


class DirectOpenAIEmbeddingModel(OpenAIEmbeddingModel):
    type: Literal["openai_embedding"]

    def model_post_init(self, context) -> None:  # pylint: disable=unused-argument
        self._client = OpenAIEmbeddings(api_key=self.api_key)

    def __str__(self):
        return f"OpenAIEmbedding('{self.model}')"


class AzureOpenAIEmbeddingModel(OpenAIEmbeddingModel):
    """AzureOpenAIEmbeddingModel configures the OpenAI embeddings client for Azure endpoints.

    It sets up the necessary endpoint, deployment, and API version for making embedding requests.
    """

    type: Literal["azure_embedding"]
    endpoint: str
    azure_deployment: str
    api_version: str

    def model_post_init(self, context) -> None:  # pylint: disable=unused-argument
        self._client = AzureOpenAIEmbeddings(
            azure_endpoint=self.endpoint,
            azure_deployment=self.azure_deployment,
            api_version=self.api_version,
            api_key=self.api_key,
        )

    def __str__(self):
        return f"AzureEmbedding('{self.model}')"
