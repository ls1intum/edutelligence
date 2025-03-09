from typing import Literal, Any

import cohere

from app.llm import LanguageModel


class CohereAzureClient(LanguageModel):
    type: Literal["cohere_azure"]
    endpoint: str

    def model_post_init(self, __context: Any) -> None:
        cohere.ClientV2(base_url=self.endpoint, api_key=self.api_key)