"""Model Inference Service: sends a chat request to a language model and returns its answer.

The interface follows the OpenAI chat format that Logos offers. For now a stub answers without
calling a model. If the request contains a JSON schema (structured output), the stub returns a
minimal JSON object that matches the schema, so the caller's parsing can be exercised.
"""

import json
from typing import Any, Optional, Protocol


class ModelInferenceService(Protocol):
    def complete(
        self, model: str, messages: list[dict[str, str]], json_schema: Optional[dict] = None
    ) -> str: ...


class StubModelInferenceService:
    """Answers without calling a model."""

    def complete(
        self, model: str, messages: list[dict[str, str]], json_schema: Optional[dict] = None
    ) -> str:
        if json_schema is None:
            return "This is a stub answer."
        return json.dumps(_example(json_schema))


def _example(schema: dict) -> Any:
    """Builds the simplest value that matches a (simple) JSON schema."""
    if "enum" in schema:
        return schema["enum"][0]
    kind = schema.get("type")
    if kind == "object":
        return {key: _example(sub) for key, sub in schema.get("properties", {}).items()}
    if kind == "array":
        return []
    if kind == "string":
        return "stub"
    if kind in ("integer", "number"):
        return 0
    if kind == "boolean":
        return False
    return None
