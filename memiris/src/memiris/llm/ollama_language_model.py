"""
Ollama-backed concrete implementation of AbstractLanguageModel.
Also provides typed wrappers for Ollama responses.
"""

import os
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Union

import langfuse
from langchain_ollama import ChatOllama
from ollama import Client, ListResponse, Message

from memiris.llm.abstract_language_model import (
    AbstractLanguageModel,
    WrappedChatResponse,
    WrappedEmbeddingResponse,
)


@dataclass
class ModelInfo:
    name: str

    @classmethod
    def from_ollama_model(cls, data: ListResponse.Model) -> "ModelInfo":
        return cls(name=data.model or "unknown")


class OllamaLanguageModel(AbstractLanguageModel):
    """Concrete language model adapter powered by Ollama."""

    def __init__(
        self,
        model: str,
        host: Optional[str] = None,
        token: Optional[str] = None,
    ) -> None:
        self._model = model
        self.host = host or os.environ.get("OLLAMA_HOST")
        self.token = token or os.environ.get("OLLAMA_TOKEN")

        self._cookies = {"token": self.token} if self.token else None
        self._client = Client(self.host, cookies=self._cookies)
        self._langfuse = langfuse.get_client()

    @property
    def model(self) -> str:
        return self._model

    def chat(
        self,
        messages: Sequence[Union[Mapping[str, Any], Message]],
        response_format: Optional[Dict[str, Any]] = None,
        keep_alive: Optional[Union[str, int]] = None,
        options: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> WrappedChatResponse:
        with self._langfuse.start_as_current_generation(
            name="ollama-chat",
            model=self._model,
            input=messages,
            model_parameters=options,
        ) as generation:
            think = "high" if self._model.startswith("gpt-oss") else None
            response = self._client.chat(
                self._model,
                messages=messages,
                format=response_format,
                keep_alive=keep_alive,
                options=options,
                think=think,  # type: ignore
                **kwargs,
            )
            generation.update(output=response.message, metadata=response)
        return WrappedChatResponse.from_ollama_response(response)

    def embed(self, text: str) -> WrappedEmbeddingResponse:
        response = self._client.embed(self._model, text)
        return WrappedEmbeddingResponse.from_ollama_response(response)

    def langchain_client(self) -> ChatOllama:
        return ChatOllama(
            model=self._model,
            base_url=self.host,
            client_kwargs={"cookies": self._cookies},
            reasoning="high" if self._model.startswith("gpt-oss") else None,  # type: ignore
        )

    # --- Model lifecycle / admin ---
    def _list(self) -> List[ModelInfo]:
        response = self._client.list()
        models = response.get("models", [])
        return [ModelInfo.from_ollama_model(model) for model in models]

    def _pull(self) -> None:
        self._client.pull(self._model)

    def _ps(self) -> List[ModelInfo]:
        response = self._client.ps()
        models = response.get("models", [])
        return [ModelInfo.from_ollama_model(model) for model in models]

    def ensure_present(self) -> None:
        models = [model_info.name for model_info in self._list()]
        if self._model not in models:
            print(f"Model {self._model} not found. Pulling...")
            self._pull()
        else:
            print(f"Model {self._model} is already present.")

    def is_loaded(self) -> bool:
        models = [model_info.name for model_info in self._ps()]
        return self._model in models

    def load(self, duration: str = "5m") -> None:
        print(f"Loading model {self._model} for {duration}...")
        self.chat(messages=[], keep_alive=duration)
        print(f"Model {self._model} loaded.")

    def unload(self) -> None:
        print(f"Unloading model {self._model}...")
        self.chat(messages=[], keep_alive=0)
        print(f"Model {self._model} unloaded.")
