from datetime import datetime
from typing import Literal, Any

from openai import OpenAI
from openai.lib.azure import AzureOpenAI
from openai.types.chat import ChatCompletionMessage, ChatCompletionMessageParam
from openai.types.chat.completion_create_params import ResponseFormat

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
        openai_content = []
        for content in message.contents:
            match content:
                case ImageMessageContentDTO():
                    openai_content.append(
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{content.base64}",
                                "detail": "high",
                            },
                        }
                    )
                case TextMessageContentDTO():
                    openai_content.append(
                        {"type": "text", "text": content.text_content}
                    )
                case JsonMessageContentDTO():
                    openai_content.append(
                        {
                            "type": "json_object",
                            "json_object": content.json_content,
                        }
                    )
                case _:
                    pass

        openai_message = {
            "role": map_role_to_str(message.sender),
            "content": openai_content,
        }
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
        # noinspection PyTypeChecker
        if arguments.response_format == "JSON":
            response = self._client.chat.completions.create(
                model=self.model,
                messages=convert_to_open_ai_messages(messages),
                temperature=arguments.temperature,
                max_tokens=arguments.max_tokens,
                response_format=ResponseFormat(type="json_object")
                )
        else:
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
