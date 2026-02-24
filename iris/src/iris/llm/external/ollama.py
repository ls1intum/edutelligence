import base64
import json
from datetime import datetime
from typing import (
    Any,
    Dict,
    Literal,
    Optional,
    Sequence,
    Type,
    Union,
)
from uuid import uuid4

from httpx import Client as HTTPXClient
from httpx import HTTPTransport, Timeout
from langchain_core.tools import BaseTool
from langchain_experimental.llms.ollama_functions import convert_to_ollama_tool
from ollama import Client, Message
from pydantic import BaseModel, Field
from requests.auth import HTTPBasicAuth

from iris.tracing import observe

from ...common.logging_config import get_logger
from ...common.message_converters import map_role_to_str, map_str_to_role
from ...common.pyris_message import PyrisAIMessage, PyrisMessage, PyrisToolMessage
from ...common.token_usage_dto import TokenUsageDTO
from ...domain.data.image_message_content_dto import ImageMessageContentDTO
from ...domain.data.json_message_content_dto import JsonMessageContentDTO
from ...domain.data.text_message_content_dto import TextMessageContentDTO
from ...domain.data.tool_call_dto import FunctionDTO, ToolCallDTO
from ...domain.data.tool_message_content_dto import ToolMessageContentDTO
from ...llm import CompletionArguments
from ...llm.external.model import ChatModel, CompletionModel, EmbeddingModel

logger = get_logger(__name__)


def convert_to_ollama_images(base64_images: list[str]) -> list[bytes] | None:
    """
    Convert a list of base64 images to a list of bytes
    """
    if not base64_images:
        return None
    return [base64.b64decode(base64_image) for base64_image in base64_images]


def convert_to_ollama_messages(messages: list[PyrisMessage]) -> list[Message]:
    """
    Convert a list of PyrisMessages to a list of Ollama Messages
    """
    messages_to_return = []
    for message in messages:
        # Handle assistant messages with tool calls
        if isinstance(message, PyrisAIMessage) and message.tool_calls:
            tool_calls = [
                {
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    }
                }
                for tc in message.tool_calls
            ]
            text_content = ""
            for content in message.contents:
                if isinstance(content, TextMessageContentDTO):
                    text_content += content.text_content
            messages_to_return.append(
                Message(
                    role="assistant",
                    content=text_content,
                    tool_calls=tool_calls,
                )
            )
            continue

        # Handle tool result messages
        if isinstance(message, PyrisToolMessage):
            for content in message.contents:
                if isinstance(content, ToolMessageContentDTO):
                    messages_to_return.append(
                        Message(
                            role="tool",
                            content=content.tool_content,
                        )
                    )
            continue

        if len(message.contents) == 0:
            continue
        text_content = ""
        images = []
        for content in message.contents:
            match content:
                case ImageMessageContentDTO():
                    images.append(content.base64)
                case TextMessageContentDTO():
                    if len(text_content) > 0:
                        text_content += "\n"
                    text_content += content.text_content
                case JsonMessageContentDTO():
                    if len(text_content) > 0:
                        text_content += "\n"
                    text_content += content.json_content
                case _:
                    continue
        messages_to_return.append(
            Message(
                role=map_role_to_str(message.sender),
                content=text_content,
                images=convert_to_ollama_images(images),
            )
        )
    return messages_to_return


def convert_to_iris_message(
    message: Message, num_input_tokens: int, num_output_tokens: int, model: str
) -> PyrisMessage:
    """
    Convert a Message to a PyrisMessage.

    When the response contains tool_calls, returns a PyrisAIMessage with
    synthetic call IDs (Ollama doesn't provide them, but LangChain requires them).
    """
    tokens = TokenUsageDTO(
        numInputTokens=num_input_tokens,
        numOutputTokens=num_output_tokens,
        model=model,
    )

    tool_calls = message.get("tool_calls") or []
    if tool_calls:
        iris_tool_calls = [
            ToolCallDTO(
                id=f"call_{uuid4().hex[:24]}",
                type="function",
                function=FunctionDTO(
                    name=tc.get("function", {}).get("name", ""),
                    arguments=json.dumps(tc.get("function", {}).get("arguments", {})),
                ),
            )
            for tc in tool_calls
        ]
        return PyrisAIMessage(
            tool_calls=iris_tool_calls,
            contents=[TextMessageContentDTO(text_content="")],
            sentAt=datetime.now(),
            token_usage=tokens,
        )

    contents = [TextMessageContentDTO(text_content=message["content"])]
    return PyrisMessage(
        sender=map_str_to_role(message["role"]),
        contents=contents,
        sentAt=datetime.now(),
        token_usage=tokens,
    )


class OllamaModel(
    CompletionModel,
    ChatModel,
    EmbeddingModel,
):
    """OllamaModel implements completion, chat, and embedding functionalities using the Ollama API.

    It configures the client with the provided host and model options, and translates responses into PyrisMessages.
    """

    type: Literal["ollama"]
    host: str
    options: dict[str, Any] = Field(default={})
    username: Optional[str] = None
    password: Optional[str] = None
    api_key: Optional[str] = None
    _client: Client

    def model_post_init(self, context) -> None:  # pylint: disable=unused-argument
        self._client = Client()

        # Use custom HTTP transport to speed up request performance and avoid default retry/backoff behavior
        timeout = Timeout(connect=10.0, read=60.0, write=10.0, pool=5.0)

        transport = HTTPTransport(retries=1)
        headers = {"Content-Type": "application/json"}
        auth = None
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        elif self.username and self.password:
            auth = HTTPBasicAuth(self.username, self.password)

        # Override the internal HTTPX client used by Ollama to enable HTTP/2 and ensure consistent authentication
        self._client._client = HTTPXClient(  # pylint: disable=protected-access
            base_url=self.host,
            http2=True,
            transport=transport,
            timeout=timeout,
            auth=auth,
            headers=headers,
        )

    @observe(name="Ollama Completion", as_type="generation")
    def complete(
        self,
        prompt: str,
        arguments: CompletionArguments,
        image: Optional[ImageMessageContentDTO] = None,
    ) -> str:
        response = self._client.generate(
            model=self.model,
            prompt=prompt,
            images=[image.base64] if image else None,
            format="json" if arguments.response_format == "JSON" else "",
            options=self.options,
        )
        return response["response"]

    # --- Tooling helpers -----------------------------------------------------

    def _convert_tools(
        self,
        tools: Optional[
            Sequence[Union[Dict[str, Any], Type[BaseModel], callable, BaseTool]]
        ],
    ) -> Optional[list]:
        """Convert tools to Ollama's API format (schema only, no executors)."""
        if not tools:
            return None

        tools_for_client: list = []

        for tool in tools:
            if isinstance(tool, BaseTool):
                schema = convert_to_ollama_tool(tool)
                tools_for_client.append({"type": "function", "function": schema})
            elif isinstance(tool, dict):
                if tool.get("type") == "function":
                    tools_for_client.append(tool)
                else:
                    tools_for_client.append({"type": "function", "function": tool})
            elif isinstance(tool, type) and issubclass(tool, BaseModel):
                schema = convert_to_ollama_tool(tool)
                tools_for_client.append({"type": "function", "function": schema})
            elif callable(tool):
                # Plain functions: Ollama converts them from docstrings
                tools_for_client.append(tool)
            else:
                logger.warning("Unsupported tool type: %s", type(tool))

        return tools_for_client or None

    @observe(name="Ollama Chat", as_type="generation")
    def chat(
        self,
        messages: list,  # list[PyrisMessage]
        arguments,  # CompletionArguments
        tools: Optional[
            Sequence[Union[Dict[str, Any], Type[BaseModel], callable, BaseTool]]
        ],
    ):
        tools_for_client = self._convert_tools(tools)
        ollama_messages = convert_to_ollama_messages(messages)

        response = self._client.chat(
            model=self.model,
            messages=ollama_messages,
            tools=tools_for_client,
            options=self.options,
        )

        msg = response.get("message", {}) or {}
        return convert_to_iris_message(
            msg,
            int(response.get("prompt_eval_count", 0) or 0),
            int(response.get("eval_count", 0) or 0),
            response.get("model", self.model),
        )

    @observe(name="Ollama Embedding", as_type="embedding")
    def embed(self, text: str) -> list[float]:
        response = self._client.embeddings(
            model=self.model, prompt=text, options=self.options
        )
        return list(response)

    def __str__(self):
        return f"Ollama('{self.model}')"
