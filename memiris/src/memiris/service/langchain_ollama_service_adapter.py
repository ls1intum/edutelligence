import inspect
import json
from typing import Any, Dict, List, Optional, Sequence

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.outputs import ChatGeneration, ChatResult

from memiris.service.ollama_wrapper import OllamaService


class ChatOllamaServiceAdapter(BaseChatModel):
    """
    Minimal LangChain BaseChatModel adapter that routes calls through OllamaService.

    This enables using LangChain agents while preserving custom auth/cookies
    handled by OllamaService.
    """

    ollama_service: OllamaService
    model: str
    options: Optional[Dict[str, Any]] = None
    bound_tools: Optional[List[Any]] = None
    openai_tools: Optional[List[Dict[str, Any]]] = None

    # Allow non-pydantic types (OllamaService) as fields
    model_config = {"arbitrary_types_allowed": True}

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[Sequence[str]] = None,
        run_manager: Optional[Any] = None,
        **kwargs: Any,
    ) -> ChatResult:
        # Map LC messages to Ollama chat format
        ollama_messages: list[dict[str, Any]] = []
        last_tool_call_id: Optional[str] = None
        for m in messages:
            if isinstance(m, SystemMessage):
                ollama_messages.append({"role": "system", "content": m.content})
            elif isinstance(m, HumanMessage):
                ollama_messages.append({"role": "user", "content": m.content})
            elif isinstance(m, ToolMessage):
                # Map LangChain tool result to Ollama tool message
                tool_msg: Dict[str, Any] = {
                    "role": "tool",
                    "content": m.content,
                }
                # Optional: include name and tool_call_id if present
                name = getattr(m, "name", None)
                if not name:
                    extra = getattr(m, "additional_kwargs", {}) or {}
                    if isinstance(extra, dict):
                        name = extra.get("name")
                if name:
                    tool_msg["name"] = name
                tool_call_id = getattr(m, "tool_call_id", None)
                if not tool_call_id:
                    extra = getattr(m, "additional_kwargs", {}) or {}
                    if isinstance(extra, dict):
                        tool_call_id = extra.get("tool_call_id")
                if not tool_call_id and last_tool_call_id:
                    tool_call_id = last_tool_call_id
                if tool_call_id:
                    tool_msg["tool_call_id"] = tool_call_id
                ollama_messages.append(tool_msg)
            else:
                # Assistant messages; include tool_calls if present for function calling context
                content_val = getattr(m, "content", "")
                msg: Dict[str, Any] = {"role": "assistant", "content": content_val}
                # Build tool_calls payload from message if present without using broad try/except
                extra = getattr(m, "additional_kwargs", {}) or {}
                tool_calls = (
                    extra.get("tool_calls") if isinstance(extra, dict) else None
                )
                if not tool_calls:
                    tool_calls = getattr(m, "tool_calls", None)
                if tool_calls:
                    normalized: List[Dict[str, Any]] = []
                    for idx, call in enumerate(tool_calls):
                        name = None
                        args_val: Any = None
                        # Accept either flattened LC schema {name, args} or OpenAI-like {function:{name,arguments}}
                        if isinstance(call, dict):
                            if "function" in call:
                                fn = call.get("function")
                                if isinstance(fn, dict):
                                    name = fn.get("name")
                                    args_val = fn.get("arguments")
                            else:
                                name = call.get("name")
                                args_val = call.get("args")
                        else:
                            # object-like
                            fn = getattr(call, "function", None)
                            if fn is not None:
                                name = getattr(fn, "name", None)
                                args_val = getattr(fn, "arguments", None)
                            else:
                                name = getattr(call, "name", None)
                                args_val = getattr(call, "args", None)
                        # Normalize args into dict for Ollama
                        if isinstance(args_val, str):
                            try:
                                args_val = json.loads(args_val)
                            except Exception:
                                args_val = {}
                        elif not isinstance(args_val, dict):
                            args_val = {}
                        call_id = None
                        if isinstance(call, dict):
                            call_id = call.get("id")
                        else:
                            call_id = getattr(call, "id", None)
                        normalized.append(
                            {
                                "id": call_id or f"call_{idx}",
                                "type": "function",
                                "function": {
                                    "name": name or "tool",
                                    "arguments": args_val,
                                },
                            }
                        )
                    if normalized:
                        msg["tool_calls"] = normalized
                        # Track last tool call id/name for potential mapping of following ToolMessage
                        last_tool_call_id = normalized[-1].get("id")
                        # Some backends expect null/absent content when tool_calls are present and no text
                        if not msg.get("content"):
                            msg["content"] = None
                ollama_messages.append(msg)

        # Call through the authenticated OllamaService
        response = self.ollama_service.chat(
            model=self.model,
            messages=ollama_messages,
            options=self.options or {"temperature": 0.05},
            tools=self.openai_tools if self.openai_tools else None,
        )

        content = response.message.content if response and response.message else ""
        ai_msg: AIMessage
        # Map Ollama tool_calls (if any) to LangChain AIMessage tool_calls format
        tool_calls = (
            getattr(response.message, "tool_calls", None)
            if response and response.message
            else None
        )
        if tool_calls:
            mapped_calls = []
            for idx, call in enumerate(tool_calls):
                name = None
                args = None
                # Support both object-like and dict-like shapes
                fn = getattr(call, "function", None) or (
                    call.get("function") if isinstance(call, dict) else None
                )
                if fn:
                    name = getattr(fn, "name", None) or (
                        fn.get("name") if isinstance(fn, dict) else None
                    )
                    args = getattr(fn, "arguments", None) or (
                        fn.get("arguments") if isinstance(fn, dict) else None
                    )
                if name is None:
                    name = getattr(call, "name", None) or (
                        call.get("name") if isinstance(call, dict) else None
                    )
                if args is None:
                    args = getattr(call, "arguments", None) or (
                        call.get("arguments") if isinstance(call, dict) else None
                    )
                # Normalize args to dict for LangChain AIMessage.tool_calls
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = {}
                elif not isinstance(args, dict):
                    args = {}
                mapped_calls.append(
                    {
                        "id": getattr(call, "id", None)
                        or (
                            call.get("id") if isinstance(call, dict) else f"call_{idx}"
                        ),
                        "name": name or "tool",
                        "args": args,
                    }
                )
            ai_msg = AIMessage(content=content or "", tool_calls=mapped_calls)
        else:
            ai_msg = AIMessage(content=content or "")
        generation = ChatGeneration(message=ai_msg)
        return ChatResult(generations=[generation])

    @property
    def _llm_type(self) -> str:  # noqa: D401
        return "ollama_service_adapter"

    # LangChain tool-calling API: allow agent to bind tools to the model
    def bind_tools(self, tools: List[Any], **kwargs: Any) -> "ChatOllamaServiceAdapter":  # type: ignore[override]
        openai_tools = [self._to_openai_tool(t) for t in tools]
        # Re-create adapter through constructor rather than mutating private fields
        return ChatOllamaServiceAdapter(
            ollama_service=self.ollama_service,
            model=self.model,
            options=self.options,
            bound_tools=[getattr(t, "func", None) or t for t in tools],
            openai_tools=openai_tools,
        )

    @staticmethod
    def _to_openai_tool(t: Any) -> Dict[str, Any]:
        name = getattr(t, "name", None) or getattr(t, "__name__", "tool")
        description = (
            getattr(t, "description", None)
            or (getattr(t, "__doc__", None) or "").strip()
        )
        schema: Dict[str, Any] | None = None
        args_schema = getattr(t, "args_schema", None)
        try:
            if args_schema is not None:
                if hasattr(args_schema, "model_json_schema"):
                    schema = args_schema.model_json_schema()
                elif hasattr(args_schema, "schema"):
                    schema = args_schema.schema()
        except Exception:
            schema = None
        if schema is None:
            try:
                func = getattr(t, "func", None) or t
                sig = inspect.signature(func)
                properties: Dict[str, Any] = {}
                required: List[str] = []
                for param_name, param in sig.parameters.items():
                    if param.kind in (
                        inspect.Parameter.VAR_POSITIONAL,
                        inspect.Parameter.VAR_KEYWORD,
                    ):
                        continue
                    ptype = "string"
                    anno = param.annotation
                    if anno in (int, "int"):
                        ptype = "integer"
                    elif anno in (float, "float"):
                        ptype = "number"
                    elif anno in (bool, "bool"):
                        ptype = "boolean"
                    elif anno in (list, "list"):
                        ptype = "array"
                    elif anno in (dict, "dict"):
                        ptype = "object"
                    properties[param_name] = {"type": ptype}
                    if param.default is inspect.Parameter.empty:
                        required.append(param_name)
                schema = {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                }
            except Exception:
                schema = {"type": "object", "properties": {}}

        return {
            "type": "function",
            "function": {
                "name": name,
                "description": description or "",
                "parameters": schema or {"type": "object", "properties": {}},
            },
        }
