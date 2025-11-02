"""
OpenAI-backed implementation of AbstractLanguageModel.
Supports both OpenAI and Azure OpenAI clients.
Includes a LangChain ChatOpenAI adapter via `langchain_openai`.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Mapping, Optional, Sequence, Union

from langchain_openai import ChatOpenAI
from openai import AzureOpenAI, OpenAI

from memiris.llm.abstract_language_model import (
    AbstractLanguageModel,
    WrappedChatResponse,
    WrappedEmbeddingResponse,
)


class OpenAiLanguageModel(AbstractLanguageModel):
    """Concrete language model adapter using OpenAI and Azure OpenAI."""

    def __init__(
        self,
        model: str,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        azure: bool = False,
        azure_endpoint: Optional[str] = None,
        api_version: Optional[str] = None,
    ) -> None:
        self._model = model
        self._azure = azure
        self._api_key = (
            api_key
            or os.environ.get("OPENAI_API_KEY")
            or os.environ.get("AZURE_OPENAI_API_KEY")
        )
        self._base_url = base_url or os.environ.get("OPENAI_BASE_URL")
        self._azure_endpoint = azure_endpoint or os.environ.get("AZURE_OPENAI_ENDPOINT")
        self._api_version = (
            api_version
            or os.environ.get("AZURE_OPENAI_API_VERSION")
            or "2024-02-15-preview"
        )
        self._client: Any = None
        if azure:
            if not self._azure_endpoint:
                raise ValueError("Azure endpoint must be provided for Azure OpenAI.")
            self._client = AzureOpenAI(
                api_key=self._api_key,
                azure_endpoint=str(self._azure_endpoint),
                api_version=self._api_version,
            )
        else:
            self._client = OpenAI(api_key=self._api_key, base_url=self._base_url)

    @property
    def model(self) -> str:
        return self._model

    def chat(
        self,
        messages: Sequence[Union[Mapping[str, Any], Any]],
        response_format: Optional[Dict[str, Any]] = None,
        keep_alive: Optional[Union[str, int]] = None,  # unused for OpenAI
        options: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> WrappedChatResponse:
        # Normalize messages to OpenAI format
        normalized: list[Dict[str, Any]] = []
        for m in messages:
            if hasattr(m, "role") and hasattr(m, "content"):
                normalized.append(
                    {"role": getattr(m, "role"), "content": getattr(m, "content")}
                )
            elif isinstance(m, Mapping):
                role = m.get("role", "user")
                content = m.get("content", "")
                name = m.get("name")
                d: Dict[str, Any] = {"role": role, "content": content}
                if name:
                    d["name"] = name
                normalized.append(d)

        temperature = (options or {}).get("temperature") if options else None

        # response_format: basic support for JSON output
        rf = None
        if response_format:
            # OpenAI v1 supports {"type": "json_object"} or json_schema
            rf = response_format

        # Build request payload and forward additional options/kwargs (e.g., tools)
        payload: Dict[str, Any] = {
            "model": self._model,
            "messages": normalized,  # type: ignore[arg-type]
        }
        if temperature is not None:
            payload["temperature"] = temperature  # type: ignore[arg-type]
        if rf:
            payload["response_format"] = rf  # type: ignore[arg-type]
        if options:
            # Do not overwrite explicit temperature if already set
            payload.update({k: v for k, v in options.items() if k != "temperature"})
        if kwargs:
            payload.update(kwargs)
        # Remove None-valued entries to avoid invalid arguments
        payload = {k: v for k, v in payload.items() if v is not None}

        resp = self._client.chat.completions.create(**payload)
        return WrappedChatResponse.from_openai_chat(resp)

    def embed(self, text: str) -> WrappedEmbeddingResponse:
        resp = self._client.embeddings.create(model=self._model, input=text)
        return WrappedEmbeddingResponse.from_openai_embedding(resp)

    def langchain_client(self) -> ChatOpenAI:
        # Let environment handle credentials; only pass model and base_url
        if self._azure:
            return ChatOpenAI(model=self._model, base_url=self._azure_endpoint)
        return ChatOpenAI(model=self._model, base_url=self._base_url)

    # --- Lifecycle helpers are not applicable for OpenAI managed service ---
    def ensure_present(self) -> None:
        pass

    def is_loaded(self) -> bool:
        return True

    def load(self, duration: str = "5m") -> None:
        pass

    def unload(self) -> None:
        pass
