import base64
import inspect
import json
import logging
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

from httpx import Client as HTTPXClient
from httpx import HTTPTransport, Timeout
from langchain_core.tools import BaseTool
from langchain_experimental.llms.ollama_functions import convert_to_ollama_tool
from ollama import Client, Message
from pydantic import BaseModel, Field
from requests.auth import HTTPBasicAuth

from ...common.message_converters import map_role_to_str, map_str_to_role
from ...common.pyris_message import PyrisMessage
from ...common.token_usage_dto import TokenUsageDTO
from ...domain.data.image_message_content_dto import ImageMessageContentDTO
from ...domain.data.json_message_content_dto import JsonMessageContentDTO
from ...domain.data.text_message_content_dto import TextMessageContentDTO
from ...llm import CompletionArguments
from ...llm.external.model import ChatModel, CompletionModel, EmbeddingModel

logger = logging.getLogger(__name__)


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
    Convert a Message to a PyrisMessage
    """
    contents = [TextMessageContentDTO(text_content=message["content"])]
    tokens = TokenUsageDTO(
        numInputTokens=num_input_tokens,
        numOutputTokens=num_output_tokens,
        model=model,
    )
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

    def _callable_to_ollama_tool(self, func: callable) -> Dict[str, Any]:
        """Create a minimal OpenAI-style tool schema for a plain callable."""
        params = {"type": "object", "properties": {}}
        sig = inspect.signature(func)
        # If the callable actually takes arguments, expose them as free-form
        # (customize here to generate a real JSON Schema if you like)
        if any(
            p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)
            for p in sig.parameters.values()
        ):
            params = {"type": "object", "additionalProperties": True}
        return {
            "name": func.__name__,
            "description": (func.__doc__ or "").strip()
            or f"Callable tool {func.__name__}",
            "parameters": params,
        }

    def _build_tooling(
        self,
        tools: Optional[
            Sequence[Union[Dict[str, Any], Type[BaseModel], callable, BaseTool]]
        ],
    ):
        """
        Returns:
          tool_defs: list[{"type":"function","function":{...}}] to send to Ollama
          executors: dict[name -> callable(args_dict)->Any]
        """
        tool_defs = []
        executors: Dict[str, callable] = {}

        if not tools:
            return None, {}

        for tool in tools:
            # Figure out the schema we send to the model…
            if callable(tool) and not isinstance(tool, BaseTool):
                schema = self._callable_to_ollama_tool(tool)
                name = schema["name"]
                tool_defs.append({"type": "function", "function": schema})

                # …and the executor we will run locally.
                def _exec_callable(args, tool_attr=tool):
                    if not args:
                        return tool_attr()
                    # Try kwargs; if it fails, try pass-through single arg
                    try:
                        return tool_attr(**args)
                    except TypeError:
                        return tool_attr(args)

                executors[name] = _exec_callable
                continue

            # Non-callable kinds: use your provided converter for the schema
            schema = convert_to_ollama_tool(tool)
            name = schema["name"]
            tool_defs.append({"type": "function", "function": schema})

            # And wire up executors for supported kinds
            if isinstance(tool, BaseTool):

                def _exec_basetool(args, tool_attr=tool):
                    if hasattr(tool_attr, "invoke"):
                        return tool_attr.invoke(args or {})
                    if hasattr(tool_attr, "run"):
                        # Some tools expect a string; give them JSON if dict
                        return tool_attr.run(
                            args if isinstance(args, str) else json.dumps(args or {})
                        )
                    raise RuntimeError(
                        f"Unsupported BaseTool without invoke/run: {type(tool_attr)}"
                    )

                executors[name] = _exec_basetool

            elif isinstance(tool, dict):
                # Bare dict tool schema provided – no executor attached.
                # You can add an executor here if you keep a separate {name: callable} registry.
                pass

            elif inspect.isclass(tool) and issubclass(tool, BaseModel):
                # Pure schema (Pydantic class) with no bound executor.
                # If you have a convention (e.g., class defines a staticmethod `run`), wire it here.
                run_fn = getattr(tool, "run", None)
                if callable(run_fn):

                    def _exec_pydantic(args, run_attr=run_fn, cls_attr=tool):
                        # Validate then run
                        instance = cls_attr.model_validate(args or {})
                        return run_attr(instance)

                    executors[name] = _exec_pydantic

        return tool_defs, executors

    def _execute_tool(self, executors: Dict[str, callable], name: str, raw_args: Any):
        # Ollama may return arguments as a JSON string or a dict
        args = raw_args
        if isinstance(raw_args, str):
            try:
                args = json.loads(raw_args) if raw_args.strip() else {}
            except Exception:
                # If it's an arbitrary string, pass it through
                args = raw_args

        exec_fn = executors.get(name)
        if not exec_fn:
            return {"error": f"Tool '{name}' has no executor bound."}

        try:
            out = exec_fn(args if isinstance(args, dict) else args)
            return out
        except Exception as e:
            return {"error": f"Exception in tool '{name}': {e}"}

    def chat(
        self,
        messages: list,  # list[PyrisMessage]
        arguments,  # CompletionArguments
        tools: Optional[
            Sequence[Union[Dict[str, Any], Type[BaseModel], callable, BaseTool]]
        ],
    ):
        # Build tool schemas for the model + executors for local runtime
        tool_defs, executors = self._build_tooling(tools)

        # Start from your converted messages, then extend with model/tool turns
        ollama_messages = convert_to_ollama_messages(messages)

        total_prompt_eval = 0
        total_eval = 0
        model_used = self.model

        for _ in range(10):
            response = self._client.chat(
                model=self.model,
                messages=ollama_messages,
                tools=tool_defs,  # pass tools every round
                format=(
                    "json"
                    if getattr(arguments, "response_format", None) == "JSON"
                    else ""
                ),
                options=self.options,
            )

            msg = response.get("message", {}) or {}
            model_used = response.get("model", self.model)
            total_prompt_eval += int(response.get("prompt_eval_count", 0) or 0)
            total_eval += int(response.get("eval_count", 0) or 0)

            tool_calls = msg.get("tool_calls") or []
            if tool_calls:
                # Add the model's tool-call message to the conversation
                ollama_messages.append(msg)

                # Execute each tool and append the tool result
                for call in tool_calls:
                    fn = call.get("function") or {}
                    name = fn.get("name")
                    args = fn.get("arguments")
                    result = self._execute_tool(executors, name, args)

                    # Stringify non-string results
                    content = (
                        result
                        if isinstance(result, str)
                        else json.dumps(result, ensure_ascii=False)
                    )

                    ollama_messages.append(
                        {
                            "role": "tool",
                            "name": name,
                            "content": content,
                        }
                    )
                # Loop again so the model can see tool outputs
                continue

            # No tool calls → we have the final assistant message
            if msg:
                ollama_messages.append(msg)
            return convert_to_iris_message(
                msg,
                total_prompt_eval,
                total_eval,
                response.get("model", model_used),
            )

        # Safety valve: max rounds reached; return whatever the last msg was
        return convert_to_iris_message(
            msg if "msg" in locals() else {},
            total_prompt_eval,
            total_eval,
            model_used,
        )

    def embed(self, text: str) -> list[float]:
        response = self._client.embeddings(
            model=self.model, prompt=text, options=self.options
        )
        return list(response)

    def __str__(self):
        return f"Ollama('{self.model}')"
