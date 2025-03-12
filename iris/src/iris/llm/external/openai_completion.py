from typing import Any, Literal

from openai import OpenAI
from openai.lib.azure import AzureOpenAI

from ...llm import CompletionArguments
from ...llm.external.model import CompletionModel


class OpenAICompletionModel(CompletionModel):
    model: str
    api_key: str
    _client: OpenAI

    def complete(self, prompt: str, arguments: CompletionArguments) -> any:
        response = self._client.completions.create(
            model=self.model,
            prompt=prompt,
            temperature=arguments.temperature,
            max_tokens=arguments.max_tokens,
            stop=arguments.stop,
        )
        return response


class DirectOpenAICompletionModel(OpenAICompletionModel):
    type: Literal["openai_completion"]

    def model_post_init(self, __context: Any) -> None:
        self._client = OpenAI(api_key=self.api_key)

    def __str__(self):
        return f"OpenAICompletion('{self.model}')"


class AzureOpenAICompletionModel(OpenAICompletionModel):
    type: Literal["azure_completion"]
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
        return f"AzureCompletion('{self.model}')"
