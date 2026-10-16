import logging
from typing import Literal, Optional

from langchain_experimental.text_splitter import SemanticChunker
from langchain_openai import AzureOpenAIEmbeddings, OpenAIEmbeddings
from openai import APIError

from iris.tracing import observe

from ...llm.external.model import EmbeddingModel
from ...llm.retry import RetryState


class OpenAIEmbeddingModel(EmbeddingModel):
    """OpenAIEmbeddingModel provides methods to generate text embeddings using the OpenAI API.

    It implements retry logic to handle API errors and supports semantic text splitting.
    """

    api_key: str
    # Optional instruction folded into a retrieval QUERY before embedding (never into
    # document text — that would cancel the asymmetric-retrieval benefit). Only a
    # deployment actually serving an instruction-tuned embedding model (e.g. a
    # Qwen3-Embedding endpoint via base_url) should set this; it is model-specific
    # calibration, not something a generic OpenAI-compatible embedding call should
    # ever apply on its own. Left unset (the default), callers embed the raw query.
    retrieval_instruction: str | None = None
    _client: OpenAIEmbeddings

    @observe(name="OpenAI Embedding", as_type="embedding")
    def embed(self, text: str) -> list[float]:
        retry_state = RetryState()
        for attempt in range(retry_state.max_attempts):
            try:
                return self._client.embed_query(text)
            except APIError as error:
                if not retry_state.should_retry(error, attempt):
                    logging.exception(
                        "OpenAI embedding error on attempt %s; not retrying",
                        attempt + 1,
                    )
                    raise
                logging.warning(
                    "OpenAI embedding error on attempt %s: %s", attempt + 1, error
                )
                retry_state.wait(error, attempt)
        raise RuntimeError(
            f"Failed to get embedding from OpenAI after {retry_state.max_attempts} attempts."
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
    """Direct OpenAI embedding model.

    If ``base_url`` is set, the client points at an OpenAI-compatible endpoint
    (e.g. a vLLM/Logos gateway); otherwise it defaults to the official OpenAI API.
    """

    type: Literal["openai_embedding"]
    base_url: Optional[str] = None

    def model_post_init(self, context) -> None:  # pylint: disable=unused-argument
        if self.base_url:
            # Non-OpenAI, OpenAI-compatible backends (e.g. vLLM, Logos) do not
            # accept the tiktoken-tokenized input path that
            # ``OpenAIEmbeddings.embed_documents`` uses by default, so we
            # disable the length-safe path and send raw strings instead.
            self._client = OpenAIEmbeddings(
                model=self.model,
                api_key=self.api_key,
                base_url=self.base_url,
                check_embedding_ctx_length=False,
            )
        else:
            self._client = OpenAIEmbeddings(model=self.model, api_key=self.api_key)

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
