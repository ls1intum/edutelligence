"""Model Inference Service: sends a chat request to a language model and returns its answer.

The interface follows the OpenAI chat format that Logos offers. Two implementations:
- StubModelInferenceService answers without calling a model. If the request contains a JSON
  schema (structured output), it returns a minimal JSON object that matches the schema.
- LogosModelInferenceService sends the request to Logos (OpenAI-compatible /chat/completions).
"""

import json
from typing import Any, Optional, Protocol

import requests

LOGOS_URL = "https://logos.aet.cit.tum.de/v1"


class ModelInferenceService(Protocol):
    def complete(
        self, model: str, messages: list[dict[str, str]], json_schema: Optional[dict] = None
    ) -> str: ...


class LogosModelInferenceService:
    """Calls a model through Logos. The API key is passed in, never stored in the repository."""

    def __init__(self, api_key: str, base_url: str = LOGOS_URL, timeout: float = 300):
        if not api_key:
            raise ValueError("no Logos API key given (set the environment variable LOGOS_API_KEY)")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def complete(
        self, model: str, messages: list[dict[str, str]], json_schema: Optional[dict] = None
    ) -> str:
        body: dict[str, Any] = {"model": model, "messages": messages}
        if json_schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "response", "strict": True, "schema": json_schema},
            }
        response = requests.post(
            f"{self.base_url}/chat/completions",
            json=body,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=self.timeout,
        )
        if response.status_code != 200:
            raise RuntimeError(f"Logos returned {response.status_code}: {response.text[:300]}")
        content = response.json()["choices"][0]["message"].get("content")
        if not content:
            raise RuntimeError("Logos returned an empty answer")
        return content


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
