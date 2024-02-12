from openai import OpenAI
from openai.lib.azure import AzureOpenAI

from llm import CompletionArguments
from llm.wrapper import AbstractLlmCompletionWrapper


class BaseOpenAICompletionWrapper(AbstractLlmCompletionWrapper):

    def __init__(self, client, model: str, **kwargs):
        super().__init__(**kwargs)
        self.client = client
        self.model = model

    def completion(self, prompt: str, arguments: CompletionArguments) -> any:
        response = self.client.completions.create(
            model=self.model,
            prompt=prompt,
            temperature=arguments.temperature,
            max_tokens=arguments.max_tokens,
            stop=arguments.stop,
        )
        return response


class OpenAICompletionWrapper(BaseOpenAICompletionWrapper):

    def __init__(self, model: str, api_key: str, **kwargs):
        client = OpenAI(api_key=api_key)
        model = model
        super().__init__(client, model, **kwargs)

    def __str__(self):
        return f"OpenAICompletion('{self.model}')"


class AzureCompletionWrapper(BaseOpenAICompletionWrapper):

    def __init__(
        self,
        model: str,
        endpoint: str,
        azure_deployment: str,
        api_version: str,
        api_key: str,
        **kwargs,
    ):
        client = AzureOpenAI(
            azure_endpoint=endpoint,
            azure_deployment=azure_deployment,
            api_version=api_version,
            api_key=api_key,
        )
        model = model
        super().__init__(client, model, **kwargs)

    def __str__(self):
        return f"AzureCompletion('{self.model}')"
