import logging
import time
from datetime import datetime
from typing import Literal, Optional

from openai import (
    OpenAI,
    APIError,
    APITimeoutError,
    RateLimitError,
    InternalServerError,
    ContentFilterFinishReasonError,
)
from openai.lib.azure import AzureOpenAI
from openai.types import CompletionUsage
from openai.types.chat import ChatCompletionMessage, ChatCompletionMessageParam
from openai.types.shared_params import ResponseFormatJSONObject

from ...common.message_converters import map_str_to_role, map_role_to_str
from app.domain.data.text_message_content_dto import TextMessageContentDTO
from ...common.pyris_message import PyrisMessage
from ...common.token_usage_dto import TokenUsageDTO
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


def convert_to_iris_message(
    message: ChatCompletionMessage, usage: Optional[CompletionUsage], model: str
) -> PyrisMessage:
    """
    Convert a ChatCompletionMessage to a PyrisMessage
    """
    num_input_tokens = getattr(usage, "prompt_tokens", 0)
    num_output_tokens = getattr(usage, "completion_tokens", 0)

    tokens = TokenUsageDTO(
        model=model,
        numInputTokens=num_input_tokens,
        numOutputTokens=num_output_tokens,
    )

    message = PyrisMessage(
        sender=map_str_to_role(message.role),
        contents=[TextMessageContentDTO(textContent=message.content)],
        sentAt=datetime.now(),
        token_usage=tokens,
    )
    return message


class OpenAIChatModel(ChatModel):
    model: str
    api_key: str

    def chat(
        self, messages: list[PyrisMessage], arguments: CompletionArguments
    ) -> PyrisMessage:
        print("Sending messages to OpenAI", messages)
        # noinspection PyTypeChecker
        retries = 5
        backoff_factor = 2
        initial_delay = 1
        client = self.get_client()
        # Maximum wait time: 1 + 2 + 4 + 8 + 16 = 31 seconds

        messages = convert_to_open_ai_messages(messages)

        for attempt in range(retries):
            try:
                if arguments.response_format == "JSON":
                    response = client.chat.completions.create(
                        model=self.model,
                        messages=messages,
                        temperature=arguments.temperature,
                        max_tokens=arguments.max_tokens,
                        response_format=ResponseFormatJSONObject(type="json_object"),
                    )
                else:
                    response = client.chat.completions.create(
                        model=self.model,
                        messages=messages,
                        temperature=arguments.temperature,
                        max_tokens=arguments.max_tokens,
                    )
                choice = response.choices[0]
                usage = response.usage
                model = response.model
                if choice.finish_reason == "content_filter":
                    # I figured that an openai error would be automatically raised if the content filter activated,
                    # but it seems that that is not the case.
                    # We don't want to retry because the same message will likely be rejected again.
                    # Raise an exception to trigger the global error handler and report a fatal error to the client.
                    raise ContentFilterFinishReasonError()
                return convert_to_iris_message(choice.message, usage, model)
            except (
                APIError,
                APITimeoutError,
                RateLimitError,
                InternalServerError,
            ):
                wait_time = initial_delay * (backoff_factor**attempt)
                logging.exception(f"OpenAI error on attempt {attempt + 1}:")
                logging.info(f"Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
        raise Exception(f"Failed to get response from OpenAI after {retries} retries")


class DirectOpenAIChatModel(OpenAIChatModel):
    type: Literal["openai_chat"]

    def get_client(self) -> OpenAI:
        return OpenAI(api_key=self.api_key)

    def __str__(self):
        return f"OpenAIChat('{self.model}')"


class AzureOpenAIChatModel(OpenAIChatModel):
    type: Literal["azure_chat"]
    endpoint: str
    azure_deployment: str
    api_version: str

    def get_client(self) -> OpenAI:
        return AzureOpenAI(
            azure_endpoint=self.endpoint,
            azure_deployment=self.azure_deployment,
            api_version=self.api_version,
            api_key=self.api_key,
        )

    def __str__(self):
        return f"AzureChat('{self.model}')"
