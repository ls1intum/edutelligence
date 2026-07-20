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
from openai.types.chat.chat_completion_message_function_tool_call import (
    ChatCompletionMessageFunctionToolCall,
    Function,
)
from openai.types.shared import ReasoningEffort
from openai.types.shared_params import ResponseFormatJSONObject
from pydantic import BaseModel, model_validator

from iris.domain.data.text_message_content_dto import TextMessageContentDTO
from iris.tracing import observe

from ...common.logging_config import get_logger
from ...common.message_converters import map_role_to_str, map_str_to_role
from ...common.pyris_message import PyrisAIMessage, PyrisMessage
from ...common.token_logprob_dto import TokenLogprobEntry, TopLogprobCandidate
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
_RETRYABLE_OPENAI_ERRORS = (RateLimitError, APIConnectionError, InternalServerError)


def _retry_after_openai_error(
    attempt: int,
    initial_delay: int,
    backoff_factor: int,
) -> None:
    wait_time = initial_delay * (backoff_factor**attempt)
    logger.exception("OpenAI error on attempt %s:", attempt + 1)
    logger.info("Retrying in %s seconds...", wait_time)
    time.sleep(wait_time)


def _is_retryable_openai_error(error: Exception) -> bool:
    if isinstance(error, _RETRYABLE_OPENAI_ERRORS):
        return True
    if isinstance(error, APIStatusError):
        return error.status_code >= 500 or error.status_code in (408, 409)
    return False


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


def _extract_token_logprobs(logprobs: Any) -> Optional[list[float]]:
    """Extract the flat list of per-token log-probabilities from a choice's
    ``logprobs`` payload, or ``None`` if they were not requested/returned."""
    content = getattr(logprobs, "content", None)
    if not content:
        return None
    return [token.logprob for token in content]


def _extract_token_logprob_entries(
    logprobs: Any,
) -> Optional[list[TokenLogprobEntry]]:
    """Extract rich per-token entries (token string + top-k alternatives) from
    a choice's ``logprobs`` payload, or ``None`` if it was not returned.

    Tolerant of backends that return plain logprobs without ``top_logprobs``:
    those entries get an empty candidate list, which confidence scoring treats
    as "uncertainty method not applicable" and falls back to mean-logprob.
    """
    content = getattr(logprobs, "content", None)
    if not content:
        return None
    return [
        TokenLogprobEntry(
            token=getattr(token, "token", "") or "",
            logprob=token.logprob,
            top_logprobs=[
                TopLogprobCandidate(token=candidate.token, logprob=candidate.logprob)
                for candidate in (getattr(token, "top_logprobs", None) or [])
            ],
        )
        for token in content
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


def raise_for_failed_responses_status(response) -> None:
    """Raise if a Responses API response ended with a failed status."""
    status = getattr(response, "status", None)
    if status != "failed":
        return

    error = getattr(response, "error", None)
    logger.error("Responses API returned failed status: %s", error)
    raise RuntimeError(f"Responses API returned failed status: {error}")


def convert_to_iris_message(
    message: ChatCompletionMessage,
    usage: Optional[CompletionUsage],
    model: str,
    logprobs: Any = None,
) -> PyrisMessage:
    """
    Convert a ChatCompletionMessage to a PyrisMessage.

    Args:
        message: The ChatCompletionMessage to convert
        usage: Optional token usage information
        model: The model name used for the completion
        logprobs: Optional ``choice.logprobs`` payload; when present its
            per-token log-probabilities are attached to the returned message.

    Returns:
        PyrisMessage or PyrisAIMessage depending on presence of tool calls
    """
    token_usage = create_token_usage(usage, model)
    current_time = datetime.now()
    content = message.content or ""

    if message.tool_calls:
        return PyrisAIMessage(
            tool_calls=create_iris_tool_calls(message.tool_calls),
            contents=[TextMessageContentDTO(textContent=content)],
            sendAt=current_time,
            token_usage=token_usage,
        )

    return PyrisMessage(
        sender=map_str_to_role(message.role),
        contents=[TextMessageContentDTO(textContent=content)],
        sendAt=current_time,
        token_usage=token_usage,
        token_logprobs=_extract_token_logprobs(logprobs),
        token_logprob_entries=_extract_token_logprob_entries(logprobs),
    )


def convert_responses_to_iris_message(
    response, model: str, fallback_output_text: str = ""
) -> PyrisMessage:
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
    raise_for_failed_responses_status(response)
    if status is not None and status != "completed":
        logger.warning("Responses API returned non-completed status: %s", status)

    token_usage = create_token_usage(
        create_completion_usage_from_responses_usage(getattr(response, "usage", None)),
        model,
    )
    current_time = datetime.now()
    output_text = extract_response_output_text(response) or fallback_output_text
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
    # Token-level log-probabilities are OPT-IN per model in llm_config.yml.
    # The defaults are False because the flags can hard-fail or silently
    # zero out a pipeline when wrong: reasoning models may reject `logprobs`
    # on chat completions with a 400, Responses-API models never produce
    # logprobs on this path, and strict OpenAI-compatible gateways reject the
    # `top_logprobs` parameter instead of ignoring it (set only
    # supports_logprobs there, keeping the mean-logprob fallback reachable).
    # Verified good for both flags: gpt-4o family, gpt-4.1 family.
    supports_logprobs: bool = False
    supports_top_logprobs: bool = False
    reasoning_effort: Optional[ReasoningEffort] = None
    reasoning_effort_values: Optional[List[ReasoningEffortValue]] = None
    # Only enable for native OpenAI/Azure endpoints that support /responses.
    # OpenAI-compatible base_url gateways such as vLLM should keep this false.
    use_responses_api: bool = False

    @model_validator(mode="after")
    def validate_logprobs_config(self):
        # The Responses API path neither requests nor extracts logprobs, so a
        # model with both flags would enter logprob confidence mode and score
        # every response 0.0 (auto-discard). Fail loudly at config load.
        if self.use_responses_api and self.supports_logprobs:
            raise ValueError(
                "supports_logprobs cannot be combined with use_responses_api: "
                "the Responses API path does not extract logprobs, so the "
                "autonomous tutor would score every response 0.0"
            )
        if self.supports_top_logprobs and not self.supports_logprobs:
            raise ValueError("supports_top_logprobs requires supports_logprobs: true")
        return self

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

    @staticmethod
    def _merge_stream_tool_calls(
        tool_call_fragments: dict[int, dict[str, Any]],
        tool_calls,
    ) -> None:
        for tool_call in tool_calls:
            index = tool_call.index
            fragment = tool_call_fragments.setdefault(
                index,
                {
                    "id": "",
                    "type": "function",
                    "function": {"name": "", "arguments": ""},
                },
            )

            if getattr(tool_call, "id", None):
                fragment["id"] = tool_call.id
            if getattr(tool_call, "type", None):
                fragment["type"] = tool_call.type

            function = getattr(tool_call, "function", None)
            if function is None:
                continue
            if getattr(function, "name", None):
                fragment["function"]["name"] += function.name
            if getattr(function, "arguments", None):
                fragment["function"]["arguments"] += function.arguments

    @staticmethod
    def _create_stream_tool_calls(
        tool_call_fragments: dict[int, dict[str, Any]],
    ) -> list[ChatCompletionMessageFunctionToolCall]:
        return [
            ChatCompletionMessageFunctionToolCall(
                id=fragment["id"],
                type=fragment["type"],
                function=Function(
                    name=fragment["function"]["name"],
                    arguments=fragment["function"]["arguments"],
                ),
            )
            for _, fragment in sorted(tool_call_fragments.items())
        ]

    def _create_streamed_chat_completion(
        self,
        client: OpenAI,
        params: dict[str, Any],
        stream_handler: Callable[[Optional[str]], None],
    ) -> PyrisMessage:
        response = client.chat.completions.create(
            **params,
            stream=True,
            stream_options={"include_usage": True},
        )
        content_parts: list[str] = []
        tool_call_fragments: dict[int, dict[str, Any]] = {}
        usage: Optional[CompletionUsage] = None
        tool_call_turn = False
        reset_sent = False

        for chunk in response:
            chunk_usage = getattr(chunk, "usage", None)
            if chunk_usage is not None:
                usage = chunk_usage

            for choice in getattr(chunk, "choices", []) or []:
                if getattr(choice, "finish_reason", None) == "content_filter":
                    raise ContentFilterFinishReasonError()

                delta = getattr(choice, "delta", None)
                if delta is None:
                    continue

                tool_calls = getattr(delta, "tool_calls", None)
                if tool_calls:
                    tool_call_turn = True
                    if not reset_sent:
                        stream_handler(None)
                        reset_sent = True
                    self._merge_stream_tool_calls(tool_call_fragments, tool_calls)
                    continue

                delta_text = getattr(delta, "content", None)
                if delta_text and not tool_call_turn:
                    content_parts.append(delta_text)
                    stream_handler(delta_text)

        if usage is None:
            logger.debug(
                "Streaming OpenAI response for model id=%s (model=%s) did not "
                "include usage information.",
                self.id,
                self.model,
            )

        message = ChatCompletionMessage(
            role="assistant",
            content="".join(content_parts),
            tool_calls=(
                self._create_stream_tool_calls(tool_call_fragments)
                if tool_call_fragments
                else None
            ),
        )
        return convert_to_iris_message(message, usage, self.model)

    def _responses_model_name(self) -> str:
        return self.model

    def _create_responses_params(
        self,
        responses_input: list[dict[str, Any]],
        arguments: CompletionArguments,
        tools: Optional[
            Sequence[Union[Dict[str, Any], Type[BaseModel], Callable, BaseTool]]
        ],
    ) -> dict[str, Any]:
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

        return params

    def _create_responses_completion(
        self,
        client: OpenAI,
        responses_input: list[dict[str, Any]],
        arguments: CompletionArguments,
        tools: Optional[
            Sequence[Union[Dict[str, Any], Type[BaseModel], Callable, BaseTool]]
        ],
    ):
        params = self._create_responses_params(responses_input, arguments, tools)
        return client.responses.create(**params)

    def _create_streamed_responses_completion(
        self,
        client: OpenAI,
        responses_input: list[dict[str, Any]],
        arguments: CompletionArguments,
        tools: Optional[
            Sequence[Union[Dict[str, Any], Type[BaseModel], Callable, BaseTool]]
        ],
        stream_handler: Callable[[Optional[str]], None],
    ) -> PyrisMessage:
        params = self._create_responses_params(responses_input, arguments, tools)
        response_stream = client.responses.create(**params, stream=True)
        content_parts: list[str] = []
        tool_call_turn = False
        reset_sent = False

        for event in response_stream:
            event_type = getattr(event, "type", None)

            if event_type == "response.output_text.delta":
                delta = getattr(event, "delta", None)
                if delta and not tool_call_turn:
                    content_parts.append(delta)
                    stream_handler(delta)
                continue

            if event_type == "response.output_item.added":
                item = getattr(event, "item", None)
                if getattr(item, "type", None) == "function_call":
                    tool_call_turn = True
                    if not reset_sent:
                        stream_handler(None)
                        reset_sent = True
                continue

            if event_type == "response.completed":
                response = getattr(event, "response", None)
                if response is None:
                    raise RuntimeError("Responses stream completed without a response")
                return convert_responses_to_iris_message(
                    response,
                    self._responses_model_name(),
                    fallback_output_text=(
                        "" if tool_call_turn else "".join(content_parts)
                    ),
                )

            if event_type == "response.incomplete":
                response = getattr(event, "response", None)
                if response is None:
                    raise RuntimeError("Responses stream incomplete without a response")
                return convert_responses_to_iris_message(
                    response,
                    self._responses_model_name(),
                    fallback_output_text=(
                        "" if tool_call_turn else "".join(content_parts)
                    ),
                )

            if event_type == "response.failed":
                response = getattr(event, "response", None)
                if response is None:
                    raise RuntimeError("Responses stream failed without a response")
                raise_for_failed_responses_status(response)
                raise RuntimeError("Responses stream failed")

        logger.debug(
            "Streaming Responses API response for model id=%s (model=%s) ended "
            "without a completion event after accumulating %s text chunks.",
            self.id,
            self.model,
            len(content_parts),
        )
        raise RuntimeError("Responses stream ended without a final response")

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
                    if arguments.stream_handler is not None:
                        return self._create_streamed_responses_completion(
                            client,
                            responses_input,
                            arguments,
                            tools,
                            arguments.stream_handler,
                        )
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

                # Token-level log-probabilities are requested only when the
                # caller opts in and the model declares support. They are
                # used downstream to derive a confidence score. The streaming
                # path does not extract per-chunk logprobs, so skip the
                # request there instead of silently dropping the payload.
                if (
                    arguments.logprobs
                    and self.supports_logprobs
                    and arguments.stream_handler is None
                ):
                    params["logprobs"] = True
                    # Top-k alternatives per token feed the uncertainty
                    # confidence method; the API caps top_logprobs at 20.
                    # Gated behind its own capability: strict backends reject
                    # unknown parameters with a 4xx instead of ignoring them,
                    # which would make the mean-logprob fallback unreachable.
                    if arguments.top_logprobs and self.supports_top_logprobs:
                        params["top_logprobs"] = max(
                            1, min(int(arguments.top_logprobs), 20)
                        )

                if arguments.response_format == "JSON":
                    params["response_format"] = ResponseFormatJSONObject(
                        type="json_object"
                    )

                if tools:
                    params["tools"] = [convert_to_openai_tool(tool) for tool in tools]
                    logger.debug("Using tools: %s", get_tool_names(tools))

                if arguments.stream_handler is not None:
                    return self._create_streamed_chat_completion(
                        client,
                        params,
                        arguments.stream_handler,
                    )

                response = client.chat.completions.create(**params)
                choice = response.choices[0]
                usage = response.usage
                if choice.finish_reason == "content_filter":
                    # I figured that an openai error would be automatically raised if the content filter activated,
                    # but it seems that that is not the case.
                    # We don't want to retry because the same message will likely be rejected again.
                    # Raise an exception to trigger the global error handler and report a fatal error to the client.
                    raise ContentFilterFinishReasonError()

                if choice.message is None or (
                    (choice.message.content is None or len(choice.message.content) == 0)
                    and not choice.message.tool_calls
                ):
                    logger.error("Model returned an empty message")
                    logger.error("Finish reason: %s", choice.finish_reason)
                    if (
                        choice.message is not None
                        and choice.message.refusal is not None
                    ):
                        logger.error("Refusal: %s", choice.message.refusal)

                return convert_to_iris_message(
                    choice.message,
                    usage,
                    self.model,
                    getattr(choice, "logprobs", None),
                )
            except (RateLimitError, APIConnectionError, InternalServerError):
                if arguments.stream_handler is not None:
                    arguments.stream_handler(None)
                _retry_after_openai_error(attempt, initial_delay, backoff_factor)
            except APIStatusError as error:
                # 408/409 are transient (the SDK's own retry predicate retries
                # them); since the client runs with max_retries=0, this loop is
                # the only retry layer.
                if _is_retryable_openai_error(error):
                    if arguments.stream_handler is not None:
                        arguments.stream_handler(None)
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
