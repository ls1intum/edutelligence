from typing import Literal, Any
from openai import OpenAI
from openai.lib.azure import AzureOpenAI

from llm import CompletionArguments
from llm.wrapper.abstract_llm_wrapper import AbstractLlmCompletionWrapper


class BaseOpenAICompletionWrapper(AbstractLlmCompletionWrapper):
    model: str
    api_key: str
    _client: OpenAI

    def completion(self, prompt: str, arguments: CompletionArguments) -> any:
        response = self._client.completions.create(
            model=self.model,
            prompt=prompt,
            temperature=arguments.temperature,
            max_tokens=arguments.max_tokens,
            stop=arguments.stop,
        )
        return response


class OpenAICompletionWrapper(BaseOpenAICompletionWrapper):
    type: Literal["openai_completion"]

    def model_post_init(self, __context: Any) -> None:
        self._client = OpenAI(api_key=self.api_key)

    def __str__(self):
        return f"OpenAICompletion('{self.model}')"


class AzureCompletionWrapper(BaseOpenAICompletionWrapper):
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
