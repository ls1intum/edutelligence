from typing import Literal

import cohere
from pydantic import BaseModel, ConfigDict

from iris.tracing import observe


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

    def model_post_init(self, context) -> None:  # pylint: disable=unused-argument
        self._client = cohere.ClientV2(base_url=self.endpoint, api_key=self.api_key)

    @observe(name="Cohere Rerank", as_type="span")
    def rerank(self, query, documents, top_n: int):
        return self._client.rerank(
            query=query, documents=documents, top_n=top_n, model=self.model
        )
