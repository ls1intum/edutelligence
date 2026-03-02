import json
import time
from datetime import datetime
from typing import (
    Any,
    Callable,
    Dict,
    Literal,
    Optional,
    Sequence,
    Type,
    Union,
)

from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from langfuse.openai import AzureOpenAI, OpenAI
from openai import APIConnectionError  # Added for retry logic
from openai import (
    APIError,
    APITimeoutError,
    ContentFilterFinishReasonError,
    RateLimitError,
)
from openai.types import CompletionUsage
from openai.types.chat import ChatCompletionMessage, ChatCompletionMessageParam
from openai.types.shared_params import ResponseFormatJSONObject
from pydantic import BaseModel

from iris.domain.data.text_message_content_dto import TextMessageContentDTO
from iris.tracing import observe

from ...common.logging_config import get_logger
from ...common.message_converters import map_role_to_str, map_str_to_role
from ...common.pyris_message import PyrisAIMessage, PyrisMessage
from ...common.token_usage_dto import TokenUsageDTO
from ...domain.data.image_message_content_dto import ImageMessageContentDTO
from ...domain.data.json_message_content_dto import JsonMessageContentDTO
from ...domain.data.tool_call_dto import ToolCallDTO
from ...domain.data.tool_message_content_dto import ToolMessageContentDTO
from ...llm import CompletionArguments
from ...llm.external.model import ChatModel

logger = get_logger(__name__)


def convert_content_to_openai_format(content):
    """Convert a single content item to OpenAI format."""
    content_type_mapping = {
        ImageMessageContentDTO: lambda c: {
            "type": "image_url",
            "image_url": {
                "url": f"data:image/jpeg;base64,{c.base64}",
                "detail": "high",
            },
        },
        TextMessageContentDTO: lambda c: {
            "type": "text",
            "text": c.text_content,
        },
        JsonMessageContentDTO: lambda c: {
            "type": "json_object",
            "json_object": c.json_content,
        },
    }

    converter = content_type_mapping.get(type(content))
    return converter(content) if converter else None


def handle_tool_message(content):
    """Handle tool-specific message conversion."""
    if isinstance(content, ToolMessageContentDTO):
        return {
            "role": "tool",
            "content": content.tool_content,
            "tool_call_id": content.tool_call_id,
        }
    return None


def create_openai_tool_calls(tool_calls):
    """Convert tool calls to OpenAI format."""
    return [
        {
            "id": tool.id,
            "type": tool.type,
            "function": {
                "name": tool.function.name,
                "arguments": json.dumps(tool.function.arguments),
            },
        }
        for tool in tool_calls
    ]


def convert_to_open_ai_messages(
    messages: list[PyrisMessage],
) -> list[ChatCompletionMessageParam]:
    """
    Convert a list of PyrisMessage to a list of ChatCompletionMessageParam.

    Args:
        messages: List of PyrisMessage objects to convert

    Returns:
        List of messages in OpenAI's format
    """
    openai_messages = []

    for message in messages:
        if message.sender == "TOOL":
            # Handle tool messages
            for content in message.contents:
                tool_message = handle_tool_message(content)
                if tool_message:
                    openai_messages.append(tool_message)
            continue

        # Handle regular messages
        openai_content = []
        for content in message.contents:
            formatted_content = convert_content_to_openai_format(content)
            if formatted_content:
                openai_content.append(formatted_content)

        # Create the message object
        openai_message = {
            "role": map_role_to_str(message.sender),
            "content": openai_content,
        }

        # Add tool calls if present
        if isinstance(message, PyrisAIMessage) and message.tool_calls:
            openai_message["tool_calls"] = create_openai_tool_calls(message.tool_calls)

        openai_messages.append(openai_message)

    return openai_messages


def create_token_usage(usage: Optional[CompletionUsage], model: str) -> TokenUsageDTO:
    """
    Create a TokenUsageDTO from CompletionUsage data.

    Args:
        usage: Optional CompletionUsage containing token counts
        model: The model name used for the completion

    Returns:
        TokenUsageDTO with the token usage information
    """
    return TokenUsageDTO(
        model=model,
        numInputTokens=getattr(usage, "prompt_tokens", 0),
        numOutputTokens=getattr(usage, "completion_tokens", 0),
    )


def create_iris_tool_calls(message_tool_calls) -> list[ToolCallDTO]:
    """
    Convert OpenAI tool calls to Iris format.

    Args:
        message_tool_calls: List of tool calls from ChatCompletionMessage

    Returns:
        List of ToolCallDTO objects
    """
    return [
        ToolCallDTO(
            id=tc.id,
            type=tc.type,
            function={
                "name": tc.function.name,
                "arguments": tc.function.arguments,
            },
        )
        for tc in message_tool_calls
    ]


def convert_to_iris_message(
    message: ChatCompletionMessage,
    usage: Optional[CompletionUsage],
    model: str,
) -> PyrisMessage:
    """
    Convert a ChatCompletionMessage to a PyrisMessage.

    Args:
        message: The ChatCompletionMessage to convert
        usage: Optional token usage information
        model: The model name used for the completion

    Returns:
        PyrisMessage or PyrisAIMessage depending on presence of tool calls
    """
    token_usage = create_token_usage(usage, model)
    current_time = datetime.now()

    if message.tool_calls:
        return PyrisAIMessage(
            tool_calls=create_iris_tool_calls(message.tool_calls),
            contents=[TextMessageContentDTO(textContent="")],
            sendAt=current_time,
            token_usage=token_usage,
        )

    return PyrisMessage(
        sender=map_str_to_role(message.role),
        contents=[TextMessageContentDTO(textContent=message.content)],
        sendAt=current_time,
        token_usage=token_usage,
    )


class OpenAIChatModel(ChatModel):
    """A chat model implementation that uses the OpenAI API for generating completions."""

    api_key: str

    @observe(name="OpenAI Chat Completion")
    def chat(
        self,
        messages: list[PyrisMessage],
        arguments: CompletionArguments,
        tools: Optional[
            Sequence[Union[Dict[str, Any], Type[BaseModel], Callable, BaseTool]]
        ],
    ) -> PyrisMessage:
        # noinspection PyTypeChecker
        retries = 5
        backoff_factor = 2
        initial_delay = 1
        client = self.get_client()
        try:
            # Maximum wait time: 1 + 2 + 4 + 8 + 16 = 31 seconds

            messages = convert_to_open_ai_messages(messages)

            for attempt in range(retries):
                try:
                    params = {"model": self.model, "messages": messages}

                    # GPT-5 reasoning models do not support temperature,
                    # top_p, or max_tokens.  Skip these for the entire
                    # GPT-5/o-series family to be safe.
                    model_lower = self.model.lower()
                    is_reasoning_model = (
                        model_lower.startswith("gpt-5")
                        or model_lower.startswith("gpt-o")
                        or model_lower.startswith("o1")
                        or model_lower.startswith("o3")
                        or model_lower.startswith("o4")
                    )

                    if arguments.temperature is not None and not is_reasoning_model:
                        params["temperature"] = arguments.temperature

                    if arguments.response_format == "JSON":
                        params["response_format"] = ResponseFormatJSONObject(
                            type="json_object"
                        )

                    if tools:
                        params["tools"] = [
                            convert_to_openai_tool(tool) for tool in tools
                        ]
                        logger.debug("Using tools: %s", [t.name for t in tools])

                    response = client.chat.completions.create(**params)
                    choice = response.choices[0]
                    usage = response.usage
                    if choice.finish_reason == "content_filter":
                        # I figured that an openai error would be automatically raised if the content filter activated,
                        # but it seems that that is not the case.
                        # We don't want to retry because the same message will likely be rejected again.
                        # Raise an exception to trigger the global error handler and report a fatal error to the client.
                        raise ContentFilterFinishReasonError()

                    if (
                        choice.message is None
                        or choice.message.content is None
                        or len(choice.message.content) == 0
                    ):
                        logger.error("Model returned an empty message")
                        logger.error("Finish reason: %s", choice.finish_reason)
                        if (
                            choice.message is not None
                            and choice.message.refusal is not None
                        ):
                            logger.error("Refusal: %s", choice.message.refusal)

                    return convert_to_iris_message(choice.message, usage, self.model)
                except (
                    APIError,
                    APITimeoutError,
                    APIConnectionError,  # Added to retry on connection errors
                    RateLimitError,
                ):
                    wait_time = initial_delay * (backoff_factor**attempt)
                    logger.exception("OpenAI error on attempt %s:", attempt + 1)
                    logger.info("Retrying in %s seconds...", wait_time)
                    time.sleep(wait_time)
            raise RuntimeError(
                f"Failed to get response from OpenAI after {retries} retries"
            )
        finally:
            # Ensure HTTP resources are released to avoid ResourceWarning on shutdown
            close = getattr(client, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    logger.debug("Failed to close OpenAI client", exc_info=True)


class DirectOpenAIChatModel(OpenAIChatModel):
    """Direct implementation of the OpenAI Chat Model."""

    type: Literal["openai_chat"]

    def get_client(self) -> OpenAI:
        return OpenAI(api_key=self.api_key)

    def __str__(self):
        return f"OpenAIChat('{self.model}')"


class AzureOpenAIChatModel(OpenAIChatModel):
    """Azure OpenAI chat model implementation."""

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
