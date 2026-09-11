import json
import time
from datetime import datetime
from typing import Any, Callable, Dict, Literal, Optional, Sequence, Type, Union
from uuid import uuid4

import requests
from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import BaseModel, Field, PrivateAttr
from requests import Response
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import HTTPError, Timeout

from iris.tracing import observe

from ...common.logging_config import get_logger
from ...common.message_converters import map_str_to_role
from ...common.pyris_message import IrisMessageRole, PyrisAIMessage, PyrisMessage
from ...common.token_logprob_dto import TokenLogprobEntry, TopLogprobCandidate
from ...common.token_usage_dto import TokenUsageDTO
from ...domain.data.image_message_content_dto import ImageMessageContentDTO
from ...domain.data.json_message_content_dto import JsonMessageContentDTO
from ...domain.data.text_message_content_dto import TextMessageContentDTO
from ...domain.data.tool_call_dto import FunctionDTO, ToolCallDTO
from ...domain.data.tool_message_content_dto import ToolMessageContentDTO
from ...llm import CompletionArguments
from ...llm.external.model import ChatModel

logger = get_logger(__name__)

DEFAULT_GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta"
REQUEST_TIMEOUT_SECONDS = 300.0
_RETRYABLE_STATUS_CODES = {408, 409, 429}
_RETRYABLE_REQUEST_ERRORS = (RequestsConnectionError, Timeout)


def _retry_after_gemini_error(
    attempt: int,
    initial_delay: int,
    backoff_factor: int,
) -> None:
    wait_time = initial_delay * (backoff_factor**attempt)
    logger.exception("Gemini API error on attempt %s:", attempt + 1)
    logger.info("Retrying in %s seconds...", wait_time)
    time.sleep(wait_time)


def _is_retryable_status(status_code: int) -> bool:
    return status_code >= 500 or status_code in _RETRYABLE_STATUS_CODES


def _decode_json(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return {"result": value}


def _json_content_to_text(content: JsonMessageContentDTO) -> str:
    if isinstance(content.json_content, str):
        return content.json_content
    return json.dumps(content.json_content)


def _parts_to_text(parts: list[dict[str, Any]]) -> str:
    return "".join(part.get("text", "") for part in parts if "text" in part)


def _normalize_schema(schema: Any) -> Any:
    if isinstance(schema, dict):
        normalized = {
            key: _normalize_schema(value)
            for key, value in schema.items()
            if key not in {"$schema", "additional_properties"}
        }
        if "type" in normalized and isinstance(normalized["type"], str):
            normalized["type"] = normalized["type"].lower()
        return normalized
    if isinstance(schema, list):
        return [_normalize_schema(item) for item in schema]
    return schema


def _content_to_gemini_part(content) -> Optional[dict[str, Any]]:
    if isinstance(content, TextMessageContentDTO):
        return {"text": content.text_content}
    if isinstance(content, JsonMessageContentDTO):
        return {"text": _json_content_to_text(content)}
    if isinstance(content, ImageMessageContentDTO):
        return {
            "inlineData": {
                "mimeType": "image/jpeg",
                "data": content.base64,
            }
        }
    return None


def _tool_message_to_gemini_part(content) -> Optional[dict[str, Any]]:
    if not isinstance(content, ToolMessageContentDTO):
        return None

    return {
        "functionResponse": {
            "id": content.tool_call_id,
            "name": content.name or content.tool_call_id,
            "response": _decode_json(content.tool_content),
        }
    }


def _tool_call_to_gemini_part(tool_call: ToolCallDTO) -> dict[str, Any]:
    return {
        "functionCall": {
            "id": tool_call.id,
            "name": tool_call.function.name,
            "args": tool_call.function.arguments,
        }
    }


def _text_system_instruction(system_parts: list[str]) -> Optional[dict[str, Any]]:
    if not system_parts:
        return None
    return {"parts": [{"text": "\n\n".join(system_parts)}]}


def convert_to_gemini_messages(
    messages: list[PyrisMessage],
) -> tuple[list[dict[str, Any]], Optional[dict[str, Any]]]:
    """
    Convert Iris messages into Gemini generateContent messages.

    Gemini accepts only user/model turns in contents, so Iris system messages
    are lifted into a single systemInstruction.
    """
    gemini_messages = []
    system_parts = []

    for message in messages:
        if message.sender in {IrisMessageRole.SYSTEM, IrisMessageRole.CTXSWAP}:
            text_parts = [
                content.text_content
                for content in message.contents
                if isinstance(content, TextMessageContentDTO)
            ]
            if text_parts:
                system_parts.append("\n".join(text_parts))
            continue

        if message.sender == IrisMessageRole.TOOL:
            parts = [
                part
                for part in (
                    _tool_message_to_gemini_part(content)
                    for content in message.contents
                )
                if part is not None
            ]
            if parts:
                gemini_messages.append({"role": "function", "parts": parts})
            continue

        if isinstance(message, PyrisAIMessage) and message.tool_calls:
            text_parts = [
                _content_to_gemini_part(content)
                for content in message.contents
                if isinstance(content, (TextMessageContentDTO, JsonMessageContentDTO))
            ]
            parts = [part for part in text_parts if part is not None]
            parts.extend(
                _tool_call_to_gemini_part(tool_call) for tool_call in message.tool_calls
            )
            if parts:
                gemini_messages.append({"role": "model", "parts": parts})
            continue

        role = "model" if message.sender == IrisMessageRole.ASSISTANT else "user"
        parts = [
            part
            for part in (
                _content_to_gemini_part(content) for content in message.contents
            )
            if part is not None
        ]
        if parts:
            gemini_messages.append({"role": role, "parts": parts})

    return gemini_messages, _text_system_instruction(system_parts)


def _convert_dict_tool_to_declaration(tool: dict[str, Any]) -> dict[str, Any]:
    if "function" in tool:
        function = tool["function"]
    else:
        function = tool

    declaration = {"name": function["name"]}
    if function.get("description"):
        declaration["description"] = function["description"]
    if function.get("parameters"):
        declaration["parameters"] = _normalize_schema(function["parameters"])
    return declaration


def convert_to_gemini_tools(
    tools: Optional[
        Sequence[Union[Dict[str, Any], Type[BaseModel], Callable, BaseTool]]
    ],
) -> Optional[list[dict[str, Any]]]:
    """Convert LangChain/OpenAI-style tools into Gemini function declarations."""
    if not tools:
        return None

    function_declarations = []
    for tool in tools:
        if isinstance(tool, dict) and "functionDeclarations" in tool:
            function_declarations.extend(tool["functionDeclarations"])
            continue
        if isinstance(tool, dict) and "function_declarations" in tool:
            function_declarations.extend(tool["function_declarations"])
            continue

        openai_tool = tool if isinstance(tool, dict) else convert_to_openai_tool(tool)
        if isinstance(openai_tool, dict) and openai_tool.get("type") == "function":
            function_declarations.append(_convert_dict_tool_to_declaration(openai_tool))
            continue
        if isinstance(openai_tool, dict) and "name" in openai_tool:
            function_declarations.append(_convert_dict_tool_to_declaration(openai_tool))
            continue

        logger.warning("Unsupported tool type for Gemini: %s", type(tool))

    if not function_declarations:
        return None
    return [{"functionDeclarations": function_declarations}]


def _usage_from_response(response: dict[str, Any], model: str) -> TokenUsageDTO:
    usage = response.get("usageMetadata", {})
    return TokenUsageDTO(
        model=model,
        numInputTokens=int(usage.get("promptTokenCount", 0) or 0),
        numOutputTokens=int(usage.get("candidatesTokenCount", 0) or 0),
    )


def _extract_tool_calls(parts: list[dict[str, Any]]) -> list[ToolCallDTO]:
    tool_calls = []
    for part in parts:
        function_call = part.get("functionCall")
        if not function_call:
            continue
        tool_calls.append(
            ToolCallDTO(
                id=function_call.get("id") or f"call_{uuid4().hex[:24]}",
                type="function",
                function=FunctionDTO(
                    name=function_call.get("name", ""),
                    arguments=json.dumps(function_call.get("args", {})),
                ),
            )
        )
    return tool_calls


def _extract_token_logprobs(candidate: dict[str, Any]) -> Optional[list[float]]:
    chosen_candidates = candidate.get("logprobsResult", {}).get("chosenCandidates", [])
    if not chosen_candidates:
        return None
    return [
        chosen_candidate["logProbability"]
        for chosen_candidate in chosen_candidates
        if "logProbability" in chosen_candidate
    ]


def _extract_token_logprob_entries(
    candidate: dict[str, Any],
) -> Optional[list[TokenLogprobEntry]]:
    logprobs_result = candidate.get("logprobsResult", {})
    chosen_candidates = logprobs_result.get("chosenCandidates", [])
    top_candidates = logprobs_result.get("topCandidates", [])
    if not chosen_candidates:
        return None

    entries = []
    for index, chosen_candidate in enumerate(chosen_candidates):
        alternatives = []
        if index < len(top_candidates):
            alternatives = top_candidates[index].get("candidates", [])
        entries.append(
            TokenLogprobEntry(
                token=chosen_candidate.get("token", "") or "",
                logprob=chosen_candidate.get("logProbability", 0),
                top_logprobs=[
                    TopLogprobCandidate(
                        token=candidate.get("token", "") or "",
                        logprob=candidate.get("logProbability", 0),
                    )
                    for candidate in alternatives
                    if "logProbability" in candidate
                ],
            )
        )
    return entries


def convert_to_iris_message(response: dict[str, Any], model: str) -> PyrisMessage:
    """
    Convert a Gemini generateContent response into an Iris message.
    """
    candidates = response.get("candidates", [])
    if not candidates:
        logger.error("Gemini returned no candidates")
        return PyrisMessage(
            sender=map_str_to_role("assistant"),
            contents=[TextMessageContentDTO(textContent="")],
            sendAt=datetime.now(),
            token_usage=_usage_from_response(response, model),
        )

    candidate = candidates[0]
    finish_reason = candidate.get("finishReason")
    if finish_reason in {
        "SAFETY",
        "RECITATION",
        "BLOCKLIST",
        "PROHIBITED_CONTENT",
        "SPII",
        "IMAGE_SAFETY",
        "IMAGE_PROHIBITED_CONTENT",
        "ESCALATION",
    }:
        raise RuntimeError(
            f"Gemini blocked the response with finishReason={finish_reason}"
        )

    parts = candidate.get("content", {}).get("parts", [])
    token_usage = _usage_from_response(response, model)
    content = _parts_to_text(parts)
    tool_calls = _extract_tool_calls(parts)

    if tool_calls:
        return PyrisAIMessage(
            tool_calls=tool_calls,
            contents=[TextMessageContentDTO(textContent=content)],
            sendAt=datetime.now(),
            token_usage=token_usage,
        )

    if not content:
        logger.error("Gemini returned an empty message")
        logger.error("Finish reason: %s", finish_reason)

    return PyrisMessage(
        sender=map_str_to_role("assistant"),
        contents=[TextMessageContentDTO(textContent=content)],
        sendAt=datetime.now(),
        token_usage=token_usage,
        token_logprobs=_extract_token_logprobs(candidate),
        token_logprob_entries=_extract_token_logprob_entries(candidate),
    )


class GoogleGeminiChatModel(ChatModel):
    """Chat model implementation for Google's Gemini generateContent API."""

    type: Literal["google_gemini"]
    api_key: str
    endpoint: str = DEFAULT_GEMINI_ENDPOINT
    supports_temperature: bool = True
    supports_logprobs: bool = False
    supports_top_logprobs: bool = False
    request_timeout_seconds: float = REQUEST_TIMEOUT_SECONDS
    generation_config: dict[str, Any] = Field(default_factory=dict)
    safety_settings: Optional[list[dict[str, Any]]] = None
    tool_config: Optional[dict[str, Any]] = None
    _session: requests.Session = PrivateAttr()

    def model_post_init(self, context) -> None:  # pylint: disable=unused-argument
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Content-Type": "application/json",
                "x-goog-api-key": self.api_key,
            }
        )

    def _model_path(self) -> str:
        return (
            self.model if self.model.startswith("models/") else f"models/{self.model}"
        )

    def _generate_content_url(self, *, stream: bool = False) -> str:
        action = "streamGenerateContent?alt=sse" if stream else "generateContent"
        endpoint = self.endpoint.rstrip("/")
        return f"{endpoint}/{self._model_path()}:{action}"

    def _create_generation_config(
        self, arguments: CompletionArguments
    ) -> dict[str, Any]:
        config = dict(self.generation_config)
        if arguments.temperature is not None and self.supports_temperature:
            config["temperature"] = arguments.temperature
        if arguments.max_tokens is not None:
            config["maxOutputTokens"] = arguments.max_tokens
        if arguments.stop is not None:
            config["stopSequences"] = arguments.stop
        if arguments.response_format == "JSON":
            config["responseMimeType"] = "application/json"
        if arguments.logprobs and self.supports_logprobs:
            config["responseLogprobs"] = True
            if arguments.top_logprobs and self.supports_top_logprobs:
                config["logprobs"] = max(0, min(int(arguments.top_logprobs), 20))
        return config

    def _create_payload(
        self,
        messages: list[PyrisMessage],
        arguments: CompletionArguments,
        tools: Optional[
            Sequence[Union[Dict[str, Any], Type[BaseModel], Callable, BaseTool]]
        ],
    ) -> dict[str, Any]:
        contents, system_instruction = convert_to_gemini_messages(messages)
        payload: dict[str, Any] = {"contents": contents}

        generation_config = self._create_generation_config(arguments)
        if generation_config:
            payload["generationConfig"] = generation_config
        if system_instruction:
            payload["systemInstruction"] = system_instruction
        if self.safety_settings:
            payload["safetySettings"] = self.safety_settings

        gemini_tools = convert_to_gemini_tools(tools)
        if gemini_tools:
            payload["tools"] = gemini_tools
            if self.tool_config:
                payload["toolConfig"] = self.tool_config

        return payload

    def _post_generate_content(
        self,
        payload: dict[str, Any],
        *,
        stream: bool = False,
    ) -> Response:
        response = self._session.post(
            self._generate_content_url(stream=stream),
            json=payload,
            timeout=self.request_timeout_seconds,
            stream=stream,
        )
        if response.status_code >= 400:
            response.raise_for_status()
        return response

    def _create_streamed_chat_completion(
        self,
        payload: dict[str, Any],
        stream_handler: Callable[[Optional[str]], None],
    ) -> PyrisMessage:
        response = self._post_generate_content(payload, stream=True)
        final_candidate: dict[str, Any] = {
            "content": {"role": "model", "parts": []},
        }
        usage_metadata: dict[str, Any] = {}
        saw_candidate = False
        tool_call_turn = False
        reset_sent = False

        for line in response.iter_lines(decode_unicode=True):
            if isinstance(line, bytes):
                line = line.decode("utf-8")
            if not line or not line.startswith("data:"):
                continue
            chunk = json.loads(line.removeprefix("data:").strip())
            if chunk.get("usageMetadata"):
                usage_metadata = chunk["usageMetadata"]

            candidates = chunk.get("candidates", [])
            if not candidates:
                continue

            saw_candidate = True
            candidate = candidates[0]
            if candidate.get("finishReason"):
                final_candidate["finishReason"] = candidate["finishReason"]

            parts = candidate.get("content", {}).get("parts", [])
            if _extract_tool_calls(parts):
                tool_call_turn = True
                if not reset_sent:
                    stream_handler(None)
                    reset_sent = True
                final_candidate["content"]["parts"].extend(parts)
                continue

            delta_text = _parts_to_text(parts)
            if delta_text and not tool_call_turn:
                final_candidate["content"]["parts"].append({"text": delta_text})
                stream_handler(delta_text)

        if not saw_candidate:
            raise RuntimeError("Gemini stream ended without a final response")

        final_response = {
            "candidates": [final_candidate],
            "usageMetadata": usage_metadata,
        }
        return convert_to_iris_message(final_response, self.model)

    @observe(name="Google Gemini Chat Completion")
    def chat(
        self,
        messages: list[PyrisMessage],
        arguments: CompletionArguments,
        tools: Optional[
            Sequence[Union[Dict[str, Any], Type[BaseModel], Callable, BaseTool]]
        ],
    ) -> PyrisMessage:
        retries = 5
        backoff_factor = 2
        initial_delay = 1
        payload = self._create_payload(messages, arguments, tools)

        for attempt in range(retries):
            try:
                if arguments.stream_handler is not None:
                    return self._create_streamed_chat_completion(
                        payload,
                        arguments.stream_handler,
                    )

                response = self._post_generate_content(payload)
                return convert_to_iris_message(response.json(), self.model)
            except _RETRYABLE_REQUEST_ERRORS:
                if arguments.stream_handler is not None:
                    arguments.stream_handler(None)
                _retry_after_gemini_error(attempt, initial_delay, backoff_factor)
            except HTTPError as error:
                status_code = getattr(error.response, "status_code", 0)
                if _is_retryable_status(status_code):
                    if arguments.stream_handler is not None:
                        arguments.stream_handler(None)
                    _retry_after_gemini_error(attempt, initial_delay, backoff_factor)
                else:
                    logger.exception(
                        "Non-retryable Gemini API status error for model id=%s "
                        "(model=%s, status_code=%s):",
                        self.id,
                        self.model,
                        status_code,
                    )
                    raise
        raise RuntimeError(
            f"Failed to get response from Gemini after {retries} retries"
        )

    def __str__(self):
        return f"GoogleGeminiChat('{self.model}')"
