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


def _default_think(model: str) -> Optional[Union[bool, str]]:
    """Default ``think`` value for models whose family needs an explicit one."""
    if model.startswith("gpt-oss"):
        return "high"
    if model.startswith("qwen3.") and not any(
        variant in model for variant in ("coder", "embed")
    ):
        # Qwen3 point releases (3.5, 3.6, 3.8, ...) think by default; LangChain's
        # ChatOllama keeps the <think> block inside the message content unless
        # reasoning is set explicitly. Coder and embedding variants cannot
        # think, and Ollama rejects think=True for them.
        return True
    return None


class OllamaLanguageModel(AbstractLanguageModel):
    """Concrete language model adapter powered by Ollama."""

    def __init__(
        self,
        model: str,
        host: Optional[str] = None,
        token: Optional[str] = None,
        think: Optional[Union[bool, str]] = None,
    ) -> None:
        """
        Args:
            think: Ollama ``think`` value. ``None`` picks the model family's
                default: gpt-oss only accepts effort levels, Qwen3 models only
                accept booleans.
        """
        self._model = model
        self._think = think if think is not None else _default_think(model)
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
            response = self._client.chat(
                self._model,
                messages=messages,
                format=response_format,
                keep_alive=keep_alive,
                options=options,
                think=self._think,  # type: ignore
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
            reasoning=self._think,  # type: ignore
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
