from typing import List, Any
from langchain_core.embeddings import Embeddings
from ...llm import RequestHandler


class IrisLangchainEmbeddingModel(Embeddings):
    """Custom langchain embedding for our own request handler"""

    def __init__(self, request_handler: RequestHandler) -> None:
        self.request_handler = request_handler

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return [self.embed_query(text) for text in texts]

    def embed_query(self, text: str) -> List[float]:
        return self.request_handler.embed(text)
