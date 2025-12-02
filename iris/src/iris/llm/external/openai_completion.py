from typing import Any, Literal, Optional

from openai import OpenAI
from openai.lib.azure import AzureOpenAI

from ...domain.data.image_message_content_dto import ImageMessageContentDTO
from ...llm.external.model import CompletionModel
from ..completion_arguments import CompletionArguments


class OpenAICompletionModel(CompletionModel):
    """OpenAICompletionModel uses the OpenAI API to generate completions based on a provided prompt and completion
    arguments."""

    api_key: str
    _client: OpenAI

    def complete(
        self,
        prompt: str,
        arguments: CompletionArguments,
        image: Optional[
            ImageMessageContentDTO
        ] = None,  # Not used - OpenAI completions API doesn't support images
    ) -> Any:
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

    def model_post_init(self, context) -> None:  # pylint: disable=unused-argument
        self._client = OpenAI(api_key=self.api_key)

    def __str__(self):
        return f"OpenAICompletion('{self.model}')"


class AzureOpenAICompletionModel(OpenAICompletionModel):
    """AzureOpenAICompletionModel configures and utilizes the Azure OpenAI endpoints for generating completions."""

    type: Literal["azure_completion"]
    endpoint: str
    azure_deployment: str
    api_version: str

    def model_post_init(self, context) -> None:  # pylint: disable=unused-argument
        self._client = AzureOpenAI(
            azure_endpoint=self.endpoint,
            azure_deployment=self.azure_deployment,
            api_version=self.api_version,
            api_key=self.api_key,
        )

    def __str__(self):
        return f"AzureCompletion('{self.model}')"
