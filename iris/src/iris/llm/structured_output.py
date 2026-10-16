"""Schema-enforced JSON output.

Pipelines that need data instead of prose pass a Pydantic model as
``CompletionArguments.response_schema``. Providers that support it enforce the
schema while decoding (OpenAI/Azure ``json_schema`` with ``strict: true``,
vLLM guided decoding, Ollama ``format``); the result is validated with the same
model. This replaces prompt-and-parse protocols such as "answer KEEP or
UPDATE: <title>".
"""

import copy
import re
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

ModelT = TypeVar("ModelT", bound=BaseModel)

_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


class StructuredOutputError(ValueError):
    """The model's output does not match the requested schema."""


_NAME_MAPS = ("properties", "$defs", "definitions")


def _make_strict(node: Any) -> Any:
    """Make a schema node strict; keys of name maps are names, not keywords."""
    if isinstance(node, list):
        return [_make_strict(item) for item in node]
    if not isinstance(node, dict):
        return node
    strict: dict[str, Any] = {}
    for key, value in node.items():
        if key in ("title", "default"):
            continue
        if key in _NAME_MAPS and isinstance(value, dict):
            strict[key] = {name: _make_strict(child) for name, child in value.items()}
        else:
            strict[key] = _make_strict(value)
    if strict.get("type") == "object" and "properties" in strict:
        strict["additionalProperties"] = False
        strict["required"] = list(strict["properties"])
    return strict


def strict_json_schema(model: type[BaseModel]) -> dict:
    """The model's JSON schema in the strict form providers require."""
    return _make_strict(copy.deepcopy(model.model_json_schema()))


def schema_name(model: type[BaseModel]) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", model.__name__)[:64]


def parse_structured_output(model: type[ModelT], text: str) -> ModelT:
    """Validate the model's JSON answer (tolerating a surrounding code fence)."""
    candidate = (text or "").strip()
    fenced = _FENCE.match(candidate)
    if fenced:
        candidate = fenced.group(1)
    try:
        return model.model_validate_json(candidate)
    except ValidationError as error:
        raise StructuredOutputError(
            f"Output does not match {model.__name__}: {error.errors()[:1]}"
        ) from error
