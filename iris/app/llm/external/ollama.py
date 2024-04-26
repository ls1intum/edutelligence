import base64
from datetime import datetime
from typing import Literal, Any, Optional

from ollama import Client, Message

from ...common.message_converters import map_role_to_str, map_str_to_role
from ...domain.data.json_message_content_dto import JsonMessageContentDTO
from ...domain.data.text_message_content_dto import TextMessageContentDTO
from ...domain.data.image_message_content_dto import ImageMessageContentDTO
from ...domain import PyrisMessage
from ...llm import CompletionArguments
from ...llm.external.model import ChatModel, CompletionModel, EmbeddingModel


def convert_to_ollama_images(base64_images: list[str]) -> list[bytes] | None:
    """
    Convert a list of base64 images to a list of bytes
    """
    if not base64_images:
        return None
    return [base64.b64decode(base64_image) for base64_image in base64_images]


def convert_to_ollama_messages(messages: list[PyrisMessage]) -> list[Message]:
    """
    Convert a list of PyrisMessage to a list of Message
    """
    messages_to_return = []
    for message in messages:
        match message.contents[0]:
            case ImageMessageContentDTO():
                messages_to_return.append(
                    Message(
                        role=map_role_to_str(message.sender),
                        content=message.contents[0].text_content,
                        images=message.contents[0].base64,
                    )
                )
            case TextMessageContentDTO():
                messages_to_return.append(
                    Message(
                        role=map_role_to_str(message.sender),
                        content=message.contents[0].text_content,
                    )
                )
            case JsonMessageContentDTO():
                messages_to_return.append(
                    Message(
                        role=map_role_to_str(message.sender),
                        content=message.contents[0].text_content,
                    )
                )
            case _:
                continue
    return messages_to_return


def convert_to_iris_message(message: Message) -> PyrisMessage:
    """
    Convert a Message to a PyrisMessage
    """
    contents = [TextMessageContentDTO(text_content=message["content"])]
    return PyrisMessage(
        sender=map_str_to_role(message["role"]),
        contents=contents,
        send_at=datetime.now(),
    )


class OllamaModel(
    CompletionModel,
    ChatModel,
    EmbeddingModel,
):
    type: Literal["ollama"]
    model: str
    host: str
    _client: Client

    def model_post_init(self, __context: Any) -> None:
        self._client = Client(host=self.host)  # TODO: Add authentication (httpx auth?)

    def complete(
        self,
        prompt: str,
        arguments: CompletionArguments,
        image: Optional[ImageMessageContentDTO] = None,
    ) -> str:
        response = self._client.generate(
            model=self.model, prompt=prompt, images=image.base64 if image else None
        )
        return response["response"]

    def chat(
        self, messages: list[PyrisMessage], arguments: CompletionArguments
    ) -> PyrisMessage:
        response = self._client.chat(
            model=self.model, messages=convert_to_ollama_messages(messages)
        )
        return convert_to_iris_message(response["message"])

    def embed(self, text: str) -> list[float]:
        response = self._client.embeddings(model=self.model, prompt=text)
        return list(response)

    def __str__(self):
        return f"Ollama('{self.model}')"
