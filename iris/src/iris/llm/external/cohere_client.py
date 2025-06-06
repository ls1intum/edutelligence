from typing import Any, Literal

import cohere
from pydantic import BaseModel, ConfigDict


class CohereAzureClient(BaseModel):
    """CohereAzureClient provides an interface to interact with the Cohere API using Azure endpoints."""

    type: Literal["cohere_azure"]
    cost_per_1k_requests: float
    model: str
    endpoint: str
    api_key: str
    id: str
    _client: cohere.ClientV2
    model_config = ConfigDict(arbitrary_types_allowed=True)

    def model_post_init(self, __context: Any) -> None:
        self._client = cohere.ClientV2(base_url=self.endpoint, api_key=self.api_key)

    def rerank(self, query, documents, top_n: int):
        return self._client.rerank(
            query=query, documents=documents, top_n=top_n, model=self.model
        )
