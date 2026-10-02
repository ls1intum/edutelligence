from typing import Literal

import cohere
from pydantic import ConfigDict

from iris.tracing import observe

from ...llm.external.model import RerankItem, RerankModel, RerankResponse


class CohereAzureClient(RerankModel):
    """CohereAzureClient provides an interface to interact with the Cohere API using Azure endpoints."""

    type: Literal["cohere_azure"]
    # Redeclared without a default (the base class defaults it to 0) so a
    # Cohere entry that omits the cost still fails loudly at startup.
    cost_per_1k_requests: float
    endpoint: str
    api_key: str
    _client: cohere.ClientV2
    model_config = ConfigDict(arbitrary_types_allowed=True)

    def model_post_init(self, context) -> None:  # pylint: disable=unused-argument
        self._client = cohere.ClientV2(base_url=self.endpoint, api_key=self.api_key)

    @observe(name="Cohere Rerank", as_type="span")
    def rerank(self, query: str, documents: list[str], top_n: int) -> RerankResponse:
        response = self._client.rerank(
            query=query, documents=documents, top_n=top_n, model=self.model
        )
        return RerankResponse(
            results=[
                RerankItem(index=item.index, relevance_score=item.relevance_score)
                for item in response.results
            ]
        )
