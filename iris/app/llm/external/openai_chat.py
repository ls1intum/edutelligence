from typing import Literal, Any, List, Dict

from openai import OpenAI
from openai.lib.azure import AzureOpenAI
from openai.types.chat import ChatCompletionMessageParam, ChatCompletionMessage

from ...domain import IrisMessage, IrisMessageRole
from ...llm import CompletionArguments
from ...llm.external.model import ChatModel


def convert_to_open_ai_messages(
    messages: list[IrisMessage],
) -> list[dict[str, Any]]:
    openai_messages = []
    for message in messages:
        if message.images:
            content = [{"type": "text", "content": message.text}]
            for image in message.images:
                content.append(
                    {
                        "type": "image_url",
                        "image_url": f"data:image/{image.type};base64,{image.base64}",
                        "detail": "high",
                    }
                )
        else:
            content = message.text
        openai_message = {"role": message.role.value, "content": content}
        openai_messages.append(openai_message)
    return openai_messages


def convert_to_iris_message(message: ChatCompletionMessage) -> IrisMessage:
    # Get IrisMessageRole from the string message.role
    message_role = IrisMessageRole(message.role)
    return IrisMessage(role=message_role, text=message.content)


class OpenAIChatModel(ChatModel):
    model: str
    api_key: str
    _client: OpenAI

    def chat(
        self, messages: list[IrisMessage], arguments: CompletionArguments
    ) -> IrisMessage:
        response = self._client.chat.completions.create(
            model=self.model,
            messages=convert_to_open_ai_messages(messages),
            temperature=arguments.temperature,
            max_tokens=arguments.max_tokens,
            stop=arguments.stop,
        )
        return convert_to_iris_message(response.choices[0].message)


class DirectOpenAIChatModel(OpenAIChatModel):
    type: Literal["openai_chat"]

    def model_post_init(self, __context: Any) -> None:
        self._client = OpenAI(api_key=self.api_key)

    def __str__(self):
        return f"OpenAIChat('{self.model}')"


class AzureOpenAIChatModel(OpenAIChatModel):
    type: Literal["azure_chat"]
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
        return f"AzureChat('{self.model}')"
