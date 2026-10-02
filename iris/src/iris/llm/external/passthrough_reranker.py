from typing import Literal, Sequence

from pydantic import BaseModel


class PassthroughReranker(BaseModel):
    """A local reranker that preserves the vector search result order.

    This model is useful when a deployment has embeddings but no dedicated
    reranking service. It deliberately performs no network request and returns
    the first ``top_n`` valid results in their existing relevance order.
    """

    type: Literal["passthrough_reranker"]
    id: str
    model: str = "passthrough"
    cost_per_1k_requests: float = 0

    def rerank(self, query: str, documents: Sequence[str], top_n: int) -> list[int]:
        """Return indices that preserve the input order, capped at ``top_n``."""
        del query
        result_count = min(max(top_n, 0), len(documents))
        return list(range(result_count))
