from datetime import datetime
from typing import Literal, Any

from ollama import Client, Message

from ...common.message_converters import map_role_to_str, map_str_to_role
from ...domain.data.text_message_content_dto import TextMessageContentDTO
from ...domain import PyrisMessage
from ...llm import CompletionArguments
from ...llm.external.model import ChatModel, CompletionModel, EmbeddingModel


def convert_to_ollama_messages(messages: list[PyrisMessage]) -> list[Message]:
    return [
        Message(
            role=map_role_to_str(message.sender),
            content=message.contents[0].text_content,
        )
        for message in messages
    ]


def convert_to_iris_message(message: Message) -> PyrisMessage:
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

    def complete(self, prompt: str, arguments: CompletionArguments) -> str:
        response = self._client.generate(model=self.model, prompt=prompt)
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
