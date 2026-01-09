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

from iris.tracing import observe

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

    def _build_tooling(
        self,
        tools: Optional[
            Sequence[Union[Dict[str, Any], Type[BaseModel], callable, BaseTool]]
        ],
    ):
        """
        Build the list we pass to Ollama and bind local executors.

        We follow Ollama's API:
          - Python functions can be passed directly; Ollama converts them to Tools
            based on Google-style docstrings.
          - Dict schemas and 'Ollama Tools' are accepted as-is.
          - For LangChain BaseTool / Pydantic models we convert to a function schema.

        Returns:
          tools_for_client: list accepted by ollama.Client.chat(..., tools=...)
          executors: dict[name -> callable(args_dict) -> Any]
        """
        if not tools:
            return None, {}

        tools_for_client: list = []
        executors: Dict[str, callable] = {}

        for tool in tools:
            # 1) Plain Python function: pass through unchanged + bind executor
            if callable(tool) and not isinstance(tool, BaseTool):
                name = getattr(tool, "__name__", tool.__class__.__name__)
                tools_for_client.append(tool)

                if not inspect.getdoc(tool):
                    logger.debug(
                        "Callable '%s' has no docstring. "
                        "Ollama converts callables using Google-style docstrings; "
                        "consider adding one for better parameter schemas.",
                        name,
                    )

                def _exec_callable(args, fn=tool):
                    if args is None:
                        return fn()
                    if isinstance(args, dict):
                        try:
                            return fn(**args)
                        except TypeError:
                            # Fallback: pass the dict as a single positional
                            return fn(args)
                    return fn(args)

                executors[name] = _exec_callable
                continue

            # 2) LangChain BaseTool → schema + executor
            if isinstance(tool, BaseTool):
                schema = convert_to_ollama_tool(tool)  # inner "function" schema
                name = schema["name"]
                tools_for_client.append({"type": "function", "function": schema})

                def _exec_basetool(args, tool_attr=tool):
                    if hasattr(tool_attr, "invoke"):
                        return tool_attr.invoke(args or {})
                    if hasattr(tool_attr, "run"):
                        return tool_attr.run(
                            args if isinstance(args, str) else json.dumps(args or {})
                        )
                    raise RuntimeError(
                        f"Unsupported BaseTool without invoke/run: {type(tool_attr)}"
                    )

                executors[name] = _exec_basetool
                continue

            # 3) Raw dict tool schema (either inner function schema or already wrapped)
            if isinstance(tool, dict):
                # Accept both {"type":"function","function":{...}} and a bare {name,parameters,...}
                if "type" in tool and tool.get("type") == "function":
                    tools_for_client.append(tool)
                else:
                    tools_for_client.append({"type": "function", "function": tool})
                # No executor unless you wire one separately
                continue

            # 4) Pydantic model class → schema (+ optional .run executor)
            if inspect.isclass(tool) and issubclass(tool, BaseModel):
                schema = convert_to_ollama_tool(tool)  # inner function schema
                name = schema["name"]
                tools_for_client.append({"type": "function", "function": schema})

                run_fn = getattr(tool, "run", None)
                if callable(run_fn):

                    def _exec_pydantic(args, run_attr=run_fn, cls_attr=tool):
                        instance = cls_attr.model_validate(args or {})
                        return run_attr(instance)

                    executors[name] = _exec_pydantic
                continue

            logger.warning("Unsupported tool type: %s", type(tool))

        return tools_for_client, executors

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

    @observe(name="Ollama Chat", as_type="generation")
    def chat(
        self,
        messages: list,  # list[PyrisMessage]
        arguments,  # CompletionArguments
        tools: Optional[
            Sequence[Union[Dict[str, Any], Type[BaseModel], callable, BaseTool]]
        ],
    ):
        # Build the list for Ollama and the local executors
        tools_for_client, executors = self._build_tooling(tools)

        # Start from your converted messages, then extend with model/tool turns
        ollama_messages = convert_to_ollama_messages(messages)

        total_prompt_eval = 0
        total_eval = 0
        model_used = self.model

        for _ in range(10):
            response = self._client.chat(
                model=self.model,
                messages=ollama_messages,
                tools=tools_for_client,
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

    @observe(name="Ollama Embedding", as_type="embedding")
    def embed(self, text: str) -> list[float]:
        response = self._client.embeddings(
            model=self.model, prompt=text, options=self.options
        )
        return list(response)

    def __str__(self):
        return f"Ollama('{self.model}')"
