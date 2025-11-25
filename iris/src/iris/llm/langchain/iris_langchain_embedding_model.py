from typing import List

from langchain_core.embeddings import Embeddings
from pydantic import Field

from ...llm import RequestHandler


class IrisLangchainEmbeddingModel(Embeddings):
    """Custom langchain embedding for our own request handler"""

    request_handler: RequestHandler = Field(...)

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return [self.embed_query(text) for text in texts]

    def embed_query(self, text: str) -> List[float]:
        return self.request_handler.embed(text)
