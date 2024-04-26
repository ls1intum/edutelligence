from datetime import datetime
from typing import Literal, Any

from openai import OpenAI
from openai.lib.azure import AzureOpenAI
from openai.types.chat import ChatCompletionMessageParam, ChatCompletionMessage

from ...common.message_converters import map_str_to_role, map_role_to_str
from app.domain.data.text_message_content_dto import TextMessageContentDTO
from ...domain import PyrisMessage
from ...domain.data.image_message_content_dto import ImageMessageContentDTO
from ...domain.data.json_message_content_dto import JsonMessageContentDTO
from ...llm import CompletionArguments
from ...llm.external.model import ChatModel


def convert_to_open_ai_messages(
    messages: list[PyrisMessage],
) -> list[ChatCompletionMessageParam]:
    """
    Convert a list of PyrisMessage to a list of ChatCompletionMessageParam
    """
    openai_messages = []
    for message in messages:
        match message.contents[0]:
            case ImageMessageContentDTO():
                content = [{"type": "text", "text": message.contents[0].prompt}]
                for image_base64 in message.contents[0].base64:
                    content.append(
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_base64}",
                                "detail": "high",
                            },
                        }
                    )
            case TextMessageContentDTO():
                content = [{"type": "text", "text": message.contents[0].text_content}]
            case JsonMessageContentDTO():
                content = [
                    {
                        "type": "json_object",
                        "json_object": message.contents[0].json_content,
                    }
                ]
            case _:
                content = [{"type": "text", "text": ""}]

        openai_message = {"role": map_role_to_str(message.sender), "content": content}
        openai_messages.append(openai_message)
    return openai_messages


def convert_to_iris_message(message: ChatCompletionMessage) -> PyrisMessage:
    """
    Convert a ChatCompletionMessage to a PyrisMessage
    """
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
