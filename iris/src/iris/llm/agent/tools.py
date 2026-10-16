"""Agent tools built from plain, typed Python functions.

A tool is described to the model by its function name, its docstring and a JSON
schema derived from its signature. The schema is always strict-compatible
(every parameter listed as required, optional parameters nullable, no extra
properties), so it can be sent with ``strict: true`` where the provider
supports it. A parameter the model leaves ``null`` falls back to the function
default.
"""

import inspect
import json
import typing
from dataclasses import dataclass
from typing import Any, Callable, Optional

from pydantic import TypeAdapter, ValidationError

_EMPTY: Any = inspect.Parameter.empty


class ToolArgumentError(ValueError):
    """The model sent arguments that do not fit the tool's parameters."""


def _strip_titles(schema: Any) -> Any:
    if isinstance(schema, dict):
        return {
            key: _strip_titles(value) for key, value in schema.items() if key != "title"
        }
    if isinstance(schema, list):
        return [_strip_titles(item) for item in schema]
    return schema


def _is_optional(annotation: Any) -> bool:
    return type(None) in typing.get_args(annotation)


def _nullable(schema: dict) -> dict:
    if "anyOf" in schema:
        if any(option.get("type") == "null" for option in schema["anyOf"]):
            return schema
        return {**schema, "anyOf": [*schema["anyOf"], {"type": "null"}]}
    return {"anyOf": [schema, {"type": "null"}]}


@dataclass(frozen=True)
class _Parameter:
    name: str
    annotation: Any
    default: Any
    adapter: TypeAdapter

    @property
    def has_default(self) -> bool:
        return self.default is not _EMPTY


@dataclass(frozen=True)
class AgentTool:
    """A callable the agent may invoke, with its model-facing description."""

    name: str
    description: str
    parameters: dict
    function: Callable[..., Any]
    _parameters: tuple[_Parameter, ...] = ()

    @classmethod
    def from_function(cls, function: Callable[..., Any]) -> "AgentTool":
        signature = inspect.signature(function)
        hints = typing.get_type_hints(inspect.unwrap(function))
        parameters: list[_Parameter] = []
        properties: dict[str, dict] = {}
        for name, parameter in signature.parameters.items():
            if parameter.kind in (
                inspect.Parameter.VAR_POSITIONAL,
                inspect.Parameter.VAR_KEYWORD,
            ):
                continue
            annotation = hints.get(name, str)
            adapter = TypeAdapter(annotation)
            schema = _strip_titles(adapter.json_schema())
            schema.pop("default", None)
            if parameter.default is not _EMPTY or _is_optional(annotation):
                schema = _nullable(schema)
            properties[name] = schema
            parameters.append(_Parameter(name, annotation, parameter.default, adapter))
        json_schema = {
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        }
        return cls(
            name=function.__name__,
            description=inspect.getdoc(function) or function.__name__,
            parameters=json_schema,
            function=function,
            _parameters=tuple(parameters),
        )

    def openai_schema(self, strict: bool = False) -> dict:
        """The Chat Completions tool definition (Responses is derived from it)."""
        function: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }
        if strict:
            function["strict"] = True
        return {"type": "function", "function": function}

    def bind_arguments(self, arguments: Optional[dict]) -> dict[str, Any]:
        """Validate the model's arguments and apply defaults for omitted/null ones."""
        arguments = dict(arguments or {})
        unknown = set(arguments) - {parameter.name for parameter in self._parameters}
        if unknown:
            raise ToolArgumentError(
                f"Unknown argument(s) for {self.name}: " + ", ".join(sorted(unknown))
            )
        bound: dict[str, Any] = {}
        for parameter in self._parameters:
            value = arguments.get(parameter.name)
            if value is None:
                if parameter.has_default:
                    continue
                if _is_optional(parameter.annotation):
                    bound[parameter.name] = None
                    continue
                raise ToolArgumentError(
                    f"Missing required argument {parameter.name!r} for {self.name}"
                )
            try:
                bound[parameter.name] = parameter.adapter.validate_python(value)
            except ValidationError as error:
                reason = error.errors()[0].get("msg", "invalid value")
                raise ToolArgumentError(
                    f"Invalid value for {parameter.name!r} of {self.name}: {reason}"
                ) from error
        return bound

    def call(self, arguments: Optional[dict]) -> Any:
        """Run the tool with validated arguments and return its raw output."""
        return self.function(**self.bind_arguments(arguments))

    def invoke(self, arguments: Optional[dict]) -> str:
        """Run the tool and return its output as the text the model reads."""
        return format_tool_output(self.call(arguments))


def format_tool_output(output: Any) -> str:
    """Render a tool result the way the model sees it (JSON for structured data)."""
    if isinstance(output, str):
        return output
    try:
        return json.dumps(output, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(output)


def tool_error_text(error: BaseException) -> str:
    """The observation the model reads when a tool fails."""
    if isinstance(error, ToolArgumentError):
        return f"Error: {error}"
    message = error.args[0] if error.args else type(error).__name__
    return str(message)
