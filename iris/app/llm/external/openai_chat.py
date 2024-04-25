from datetime import datetime
from typing import Literal, Any

from openai import OpenAI
from openai.lib.azure import AzureOpenAI
from openai.types.chat import ChatCompletionMessageParam, ChatCompletionMessage

from ...common.message_converters import map_role_to_str, map_str_to_role
from app.domain.data.text_message_content_dto import TextMessageContentDTO
from ...domain import PyrisMessage
from ...llm import CompletionArguments
from ...llm.external.model import ChatModel


def convert_to_open_ai_messages(
    messages: list[PyrisMessage],
) -> list[ChatCompletionMessageParam]:
    return [
        {
            "role": map_role_to_str(message.sender),
            "content": message.contents[0].text_content,
        }
        for message in messages
    ]


def convert_to_iris_message(message: ChatCompletionMessage) -> PyrisMessage:
    return PyrisMessage(
        sender=map_str_to_role(message.role),
        contents=[TextMessageContentDTO(textContent=message.content)],
        send_at=datetime.now(),
    )


class OpenAIChatModel(ChatModel):
    model: str
    api_key: str
    _client: OpenAI

    def chat(
        self, messages: list[PyrisMessage], arguments: CompletionArguments
    ) -> PyrisMessage:
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
