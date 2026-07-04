import json
import time
from datetime import datetime
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Literal,
    Optional,
    Sequence,
    Type,
    Union,
    cast,
)

from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from langfuse.openai import AzureOpenAI, OpenAI
from openai import (
    APIConnectionError,
    APIError,
    APIStatusError,
    ContentFilterFinishReasonError,
    InternalServerError,
    RateLimitError,
)
from openai.types import CompletionUsage
from openai.types.chat import ChatCompletionMessage, ChatCompletionMessageParam
from openai.types.shared import ReasoningEffort
from openai.types.shared_params import ResponseFormatJSONObject
from pydantic import BaseModel, model_validator

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

# Per-request cap for a single completion HTTP call. Artemis chat jobs expire
# after 300s, so any response slower than this could never be delivered anyway
# (the SDK default of 600s just burns the whole job on a hung connection).
REQUEST_TIMEOUT_SECONDS = 300.0

_REASONING_EFFORT_ORDER = ("none", "minimal", "low", "medium", "high", "xhigh")
ReasoningEffortValue = Literal["none", "minimal", "low", "medium", "high", "xhigh"]
_REASONING_EFFORT_INDEX = {
    effort: index for index, effort in enumerate(_REASONING_EFFORT_ORDER)
}


def _retry_after_openai_error(
    attempt: int,
    initial_delay: int,
    backoff_factor: int,
) -> None:
    wait_time = initial_delay * (backoff_factor**attempt)
    logger.exception("OpenAI error on attempt %s:", attempt + 1)
    logger.info("Retrying in %s seconds...", wait_time)
    time.sleep(wait_time)


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


def convert_content_to_responses_format(content):
    """Convert a single content item to OpenAI Responses format."""
    content_type_mapping = {
        ImageMessageContentDTO: lambda c: {
            "type": "input_image",
            "image_url": f"data:image/jpeg;base64,{c.base64}",
            "detail": "high",
        },
        TextMessageContentDTO: lambda c: {
            "type": "input_text",
            "text": c.text_content,
        },
        JsonMessageContentDTO: lambda c: {
            "type": "input_text",
            "text": json.dumps(c.json_content),
        },
    }

    converter = content_type_mapping.get(type(content))
    return converter(content) if converter else None


def create_responses_message_content(contents):
    """Convert Pyris message content to a Responses message content field."""
    text_parts = []
    formatted_content = []
    has_non_text_content = False

    for content in contents:
        if isinstance(content, TextMessageContentDTO):
            text_parts.append(content.text_content)
            continue

        formatted = convert_content_to_responses_format(content)
        if formatted:
            has_non_text_content = True
            formatted_content.append(formatted)

    if not has_non_text_content:
        return "".join(text_parts)

    return [
        {"type": "input_text", "text": text_part}
        for text_part in text_parts
        if text_part
    ] + formatted_content


def has_responses_message_content(content) -> bool:
    """Return whether a Responses message content field carries visible content."""
    if isinstance(content, str):
        return bool(content)
    return bool(content)


def create_responses_tool_calls(tool_calls):
    """Convert tool calls to Responses function_call input items."""
    return [
        {
            "type": "function_call",
            "call_id": tool.id,
            "name": tool.function.name,
            "arguments": json.dumps(tool.function.arguments),
        }
        for tool in tool_calls
    ]


def handle_responses_tool_message(content):
    """Handle tool result conversion for Responses input."""
    if isinstance(content, ToolMessageContentDTO):
        return {
            "type": "function_call_output",
            "call_id": content.tool_call_id,
            "output": content.tool_content,
        }
    return None


def convert_to_responses_input(messages: list[PyrisMessage]) -> list[dict[str, Any]]:
    """
    Convert a list of PyrisMessage to a Responses API input array.

    Args:
        messages: List of PyrisMessage objects to convert

    Returns:
        List of Responses input items
    """
    responses_input = []

    for message in messages:
        if message.sender == "TOOL":
            for content in message.contents:
                tool_message = handle_responses_tool_message(content)
                if tool_message:
                    responses_input.append(tool_message)
            continue

        message_content = create_responses_message_content(message.contents)
        if has_responses_message_content(message_content):
            responses_input.append(
                {
                    "role": map_role_to_str(message.sender),
                    "content": message_content,
                }
            )

        if isinstance(message, PyrisAIMessage) and message.tool_calls:
            responses_input.extend(create_responses_tool_calls(message.tool_calls))

    return responses_input


def convert_to_responses_tool(tool) -> dict[str, Any]:
    """Convert a LangChain/OpenAI tool definition to Responses tool format."""
    openai_tool = convert_to_openai_tool(tool)
    if openai_tool.get("type") != "function":
        return openai_tool

    function = openai_tool["function"]
    responses_tool = {
        "type": "function",
        "name": function["name"],
        "parameters": function.get("parameters"),
    }
    if "description" in function:
        responses_tool["description"] = function["description"]
    if "strict" in function:
        responses_tool["strict"] = function["strict"]
    return responses_tool


def get_tool_names(tools) -> list[str]:
    """Extract tool names for debug logging without constraining tool shape."""
    names = []
    for tool in tools:
        if isinstance(tool, dict):
            function = tool.get("function", {})
            names.append(function.get("name", str(tool)))
            continue
        names.append(getattr(tool, "name", getattr(tool, "__name__", str(tool))))
    return names


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


def create_completion_usage_from_responses_usage(usage) -> Optional[CompletionUsage]:
    """Create CompletionUsage from Responses usage data."""
    if usage is None:
        return None

    input_tokens = getattr(usage, "input_tokens", 0)
    output_tokens = getattr(usage, "output_tokens", 0)
    return CompletionUsage(
        prompt_tokens=input_tokens,
        completion_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
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


def create_iris_tool_calls_from_responses(output_items) -> list[ToolCallDTO]:
    """
    Convert Responses function_call output items to Iris format.

    Args:
        output_items: List of output items from a Responses API response

    Returns:
        List of ToolCallDTO objects
    """
    return [
        ToolCallDTO(
            id=item.call_id,
            type="function",
            function={
                "name": item.name,
                "arguments": item.arguments,
            },
        )
        for item in output_items
        if getattr(item, "type", None) == "function_call"
    ]


def response_has_refusal(output_items) -> bool:
    """Return whether a Responses output contains a refusal content item."""
    for item in output_items:
        if getattr(item, "type", None) != "message":
            continue
        for content in getattr(item, "content", []):
            if getattr(content, "type", None) == "refusal":
                return True
    return False


def extract_response_output_text(response) -> str:
    """Extract visible text from a Responses API response."""
    output_text = getattr(response, "output_text", None)
    if output_text:
        return output_text

    texts = []
    for item in getattr(response, "output", []):
        if getattr(item, "type", None) != "message":
            continue
        for content in getattr(item, "content", []):
            if getattr(content, "type", None) == "output_text":
                texts.append(content.text)
    return "".join(texts)


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


def convert_responses_to_iris_message(response, model: str) -> PyrisMessage:
    """
    Convert a Responses API response to a PyrisMessage.

    Args:
        response: The Responses API response to convert
        model: The model name used for the completion

    Returns:
        PyrisMessage or PyrisAIMessage depending on presence of function calls
    """
    output_items = getattr(response, "output", [])
    if response_has_refusal(output_items):
        raise ContentFilterFinishReasonError()

    status = getattr(response, "status", None)
    if status is not None and status != "completed":
        logger.warning("Responses API returned non-completed status: %s", status)

    token_usage = create_token_usage(
        create_completion_usage_from_responses_usage(getattr(response, "usage", None)),
        model,
    )
    current_time = datetime.now()
    output_text = extract_response_output_text(response)
    tool_calls = create_iris_tool_calls_from_responses(output_items)

    if tool_calls:
        return PyrisAIMessage(
            tool_calls=tool_calls,
            contents=[TextMessageContentDTO(textContent=output_text)],
            sendAt=current_time,
            token_usage=token_usage,
        )

    return PyrisMessage(
        sender=map_str_to_role("assistant"),
        contents=[TextMessageContentDTO(textContent=output_text)],
        sendAt=current_time,
        token_usage=token_usage,
    )


class OpenAIChatModel(ChatModel):
    """A chat model implementation that uses the OpenAI API for generating completions."""

    api_key: str
    supports_temperature: bool = True
    supports_reasoning_effort: bool = False
    reasoning_effort: Optional[ReasoningEffort] = None
    reasoning_effort_values: Optional[List[ReasoningEffortValue]] = None
    # Only enable for native OpenAI/Azure endpoints that support /responses.
    # OpenAI-compatible base_url gateways such as vLLM should keep this false.
    use_responses_api: bool = False

    @model_validator(mode="after")
    def validate_reasoning_effort_config(self):
        if not self.supports_reasoning_effort and (
            self.reasoning_effort is not None
            or self.reasoning_effort_values is not None
        ):
            raise ValueError(
                "supports_reasoning_effort must be true when reasoning_effort "
                "or reasoning_effort_values is configured"
            )

        allowed_reasoning_efforts = self.reasoning_effort_values
        if allowed_reasoning_efforts is not None and not allowed_reasoning_efforts:
            raise ValueError(
                "reasoning_effort_values must not be empty when configured"
            )
        if self.reasoning_effort is not None and allowed_reasoning_efforts is not None:
            allowed_values = cast(list[str], allowed_reasoning_efforts)
            try:
                allowed_values.index(self.reasoning_effort)
            except ValueError as error:
                raise ValueError(
                    f"reasoning_effort={self.reasoning_effort} must be one of "
                    f"reasoning_effort_values={allowed_reasoning_efforts}"
                ) from error

        return self

    def _effective_reasoning_effort(
        self,
        arguments: CompletionArguments,
    ) -> Optional[str]:
        effective = (
            arguments.reasoning_effort
            if arguments.reasoning_effort is not None
            else self.reasoning_effort
        )

        if effective is None:
            return None

        if not self.supports_reasoning_effort:
            logger.debug(
                "Ignoring reasoning_effort=%s for model id=%s "
                "(model=%s): set supports_reasoning_effort: true "
                "in llm_config.yml if this model actually supports it.",
                effective,
                self.id,
                self.model,
            )
            return None

        allowed_values = cast(list[str], self.reasoning_effort_values or [])
        if allowed_values and effective not in allowed_values:
            clamped = self._nearest_reasoning_effort(effective, allowed_values)
            logger.warning(
                "Clamping reasoning_effort=%s to %s for model id=%s "
                "(model=%s): requested value is not in reasoning_effort_values=%s.",
                effective,
                clamped,
                self.id,
                self.model,
                allowed_values,
            )
            return clamped

        return effective

    @staticmethod
    def _nearest_reasoning_effort(requested: str, allowed_values: list[str]) -> str:
        requested_index = _REASONING_EFFORT_INDEX[requested]
        return min(
            allowed_values,
            key=lambda value: (
                abs(_REASONING_EFFORT_INDEX[value] - requested_index),
                _REASONING_EFFORT_INDEX[value],
            ),
        )

    def _responses_model_name(self) -> str:
        return self.model

    def _create_responses_completion(
        self,
        client: OpenAI,
        responses_input: list[dict[str, Any]],
        arguments: CompletionArguments,
        tools: Optional[
            Sequence[Union[Dict[str, Any], Type[BaseModel], Callable, BaseTool]]
        ],
    ):
        params: dict[str, Any] = {
            "model": self._responses_model_name(),
            "input": responses_input,
            "store": False,
        }

        if arguments.temperature is not None and self.supports_temperature:
            params["temperature"] = arguments.temperature

        effective_reasoning_effort = self._effective_reasoning_effort(arguments)
        if effective_reasoning_effort is not None:
            params["reasoning"] = {"effort": effective_reasoning_effort}

        if arguments.max_tokens is not None:
            params["max_output_tokens"] = arguments.max_tokens

        if arguments.response_format == "JSON":
            params["text"] = {"format": {"type": "json_object"}}

        if tools:
            params["tools"] = [convert_to_responses_tool(tool) for tool in tools]
            logger.debug("Using tools: %s", get_tool_names(tools))

        return client.responses.create(**params)

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
        # Maximum wait time: 1 + 2 + 4 + 8 + 16 = 31 seconds

        if self.use_responses_api:
            responses_input = convert_to_responses_input(messages)
        else:
            messages = convert_to_open_ai_messages(messages)

        for attempt in range(retries):
            try:
                if self.use_responses_api:
                    response = self._create_responses_completion(
                        client,
                        responses_input,
                        arguments,
                        tools,
                    )
                    return convert_responses_to_iris_message(
                        response,
                        self._responses_model_name(),
                    )

                params: dict[str, Any] = {"model": self.model, "messages": messages}

                # Reasoning models (GPT-5 / o-series) reject the
                # `temperature` parameter. Each model declares whether it
                # accepts temperature via `supports_temperature` in
                # llm_config.yml so we don't rely on name heuristics.
                if arguments.temperature is not None and self.supports_temperature:
                    params["temperature"] = arguments.temperature

                effective_reasoning_effort = self._effective_reasoning_effort(arguments)
                if effective_reasoning_effort is not None:
                    params["reasoning_effort"] = effective_reasoning_effort

                if arguments.max_tokens is not None:
                    params["max_completion_tokens"] = arguments.max_tokens

                if arguments.response_format == "JSON":
                    params["response_format"] = ResponseFormatJSONObject(
                        type="json_object"
                    )

                if tools:
                    params["tools"] = [convert_to_openai_tool(tool) for tool in tools]
                    logger.debug("Using tools: %s", get_tool_names(tools))

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
            except (RateLimitError, APIConnectionError, InternalServerError):
                _retry_after_openai_error(attempt, initial_delay, backoff_factor)
            except APIStatusError as error:
                # 408/409 are transient (the SDK's own retry predicate retries
                # them); since the client runs with max_retries=0, this loop is
                # the only retry layer.
                if error.status_code >= 500 or error.status_code in (408, 409):
                    _retry_after_openai_error(attempt, initial_delay, backoff_factor)
                else:
                    logger.exception(
                        "Non-retryable OpenAI API status error for model id=%s "
                        "(model=%s, status_code=%s):",
                        self.id,
                        self.model,
                        error.status_code,
                    )
                    raise
            except APIError:
                logger.exception(
                    "Non-retryable OpenAI API error for model id=%s (model=%s):",
                    self.id,
                    self.model,
                )
                raise
        raise RuntimeError(
            f"Failed to get response from OpenAI after {retries} retries"
        )


class DirectOpenAIChatModel(OpenAIChatModel):
    """Direct implementation of the OpenAI Chat Model.

    If ``base_url`` is set, the client points at an OpenAI-compatible endpoint
    (e.g. a vLLM/Logos gateway); otherwise it defaults to the official OpenAI API.
    """

    type: Literal["openai_chat"]
    base_url: Optional[str] = None
    _client: OpenAI

    def model_post_init(self, context) -> None:  # pylint: disable=unused-argument
        # One client per model entry for the process lifetime: keeps the HTTP
        # connection pool warm across requests instead of paying a new TCP+TLS
        # handshake on every single completion call. max_retries=0 because the
        # retry loop in chat() already handles retries with backoff; the SDK
        # default of 2 would multiply attempts.
        if self.base_url:
            self._client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=REQUEST_TIMEOUT_SECONDS,
                max_retries=0,
            )
        else:
            self._client = OpenAI(
                api_key=self.api_key,
                timeout=REQUEST_TIMEOUT_SECONDS,
                max_retries=0,
            )

    def get_client(self) -> OpenAI:
        return self._client

    def __str__(self):
        return f"OpenAIChat('{self.model}')"


class AzureOpenAIChatModel(OpenAIChatModel):
    """Azure OpenAI chat model implementation."""

    type: Literal["azure_chat"]
    endpoint: str
    azure_deployment: str
    api_version: str
    _client: OpenAI

    def model_post_init(self, context) -> None:  # pylint: disable=unused-argument
        # See DirectOpenAIChatModel.model_post_init for the client-reuse rationale.
        if self.use_responses_api:
            self._client = OpenAI(
                base_url=self.endpoint.rstrip("/") + "/openai/v1",
                api_key=self.api_key,
                default_headers={"api-key": self.api_key},
                timeout=REQUEST_TIMEOUT_SECONDS,
                max_retries=0,
            )
            return

        self._client = AzureOpenAI(
            azure_endpoint=self.endpoint,
            azure_deployment=self.azure_deployment,
            api_version=self.api_version,
            api_key=self.api_key,
            timeout=REQUEST_TIMEOUT_SECONDS,
            max_retries=0,
        )

    def get_client(self) -> OpenAI:
        return self._client

    def _responses_model_name(self) -> str:
        return self.azure_deployment

    def __str__(self):
        return f"AzureChat('{self.model}')"
