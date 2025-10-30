"""
Typed wrappers around the Ollama client.
Provides `OllamaChatModel`, a self-contained proxy bound to a specific model
with helpers for chat, embeddings, LangChain adapter, and model lifecycle.
"""

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Union

import langfuse
from langchain_ollama import ChatOllama
from ollama import ChatResponse as OllamaChatResponse
from ollama import Client, EmbedResponse, ListResponse, Message


@dataclass
class WrappedChatResponse:
    """Wrapper for ollama chat response"""

    message: Message
    model: str
    created_at: str
    done: bool
    total_duration: int
    load_duration: int
    prompt_eval_count: int
    prompt_eval_duration: int
    eval_count: int
    eval_duration: int
    raw_response: Any

    @classmethod
    def from_ollama_response(
        cls, response: OllamaChatResponse
    ) -> "WrappedChatResponse":
        """Create a WrappedChatResponse from an ollama response"""
        response_dict = response.__dict__ if hasattr(response, "__dict__") else response
        return cls(
            message=response_dict.get("message", {}),
            model=response_dict.get("model", ""),
            created_at=response_dict.get("created_at", ""),
            done=response_dict.get("done", False),
            total_duration=response_dict.get("total_duration", 0),
            load_duration=response_dict.get("load_duration", 0),
            prompt_eval_count=response_dict.get("prompt_eval_count", 0),
            prompt_eval_duration=response_dict.get("prompt_eval_duration", 0),
            eval_count=response_dict.get("eval_count", 0),
            eval_duration=response_dict.get("eval_duration", 0),
            raw_response=response,
        )


@dataclass
class WrappedEmbeddingResponse:
    """Wrapper for ollama embedding response"""

    embeddings: Sequence[Sequence[float]]
    model: str
    raw_response: Any

    @classmethod
    def from_ollama_response(
        cls, response: EmbedResponse
    ) -> "WrappedEmbeddingResponse":
        """Create an WrappedEmbeddingResponse from an ollama response"""
        response_dict = response.__dict__ if hasattr(response, "__dict__") else response
        return cls(
            embeddings=response_dict.get("embeddings", []),
            model=response_dict.get("model", ""),
            raw_response=response,
        )


@dataclass
class ModelInfo:
    """Model information"""

    name: str

    @classmethod
    def from_ollama_model(cls, data: ListResponse.Model) -> "ModelInfo":
        """Create a ModelInfo from ollama model data"""
        return cls(
            name=data.model or "unknown",
        )


class AbstractLanguageModel(ABC):
    """
    Abstract base class for an Ollama-bound chat model.
    Defines the interface used throughout the codebase.
    """

    @property
    @abstractmethod
    def model(self) -> str:  # pragma: no cover - interface only
        """The bound Ollama model name."""
        raise NotImplementedError

    @abstractmethod
    def chat(
        self,
        messages: Sequence[Union[Mapping[str, Any], Message]],
        response_format: Optional[Dict[str, Any]] = None,
        keep_alive: Optional[Union[str, int]] = None,
        options: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> WrappedChatResponse:  # pragma: no cover - interface only
        """Send a chat request to the bound model."""
        raise NotImplementedError

    @abstractmethod
    def embed(self, text: str) -> WrappedEmbeddingResponse:  # pragma: no cover
        """Generate embeddings using the bound model."""
        raise NotImplementedError

    @abstractmethod
    def langchain_client(self) -> ChatOllama:  # pragma: no cover
        """Get a LangChain ChatOllama client for the bound model."""
        raise NotImplementedError

    @abstractmethod
    def ensure_present(self) -> None:  # pragma: no cover
        """Ensure the bound model is available locally (pull if missing)."""
        raise NotImplementedError

    @abstractmethod
    def is_loaded(self) -> bool:  # pragma: no cover
        """Check if the bound model is currently loaded."""
        raise NotImplementedError

    @abstractmethod
    def load(self, duration: str = "5m") -> None:  # pragma: no cover
        """Load the bound model for the given duration."""
        raise NotImplementedError

    @abstractmethod
    def unload(self) -> None:  # pragma: no cover
        """Unload the bound model from memory."""
        raise NotImplementedError


class OllamaLanguageModel(AbstractLanguageModel):
    """
    Proxy wrapper that bundles a specific model and acts directly against Ollama.

    Exposes high-level methods that operate on the bound `model`:
    - chat(messages, ...)
    - embed(text)
    - langchain_client()
    - ensure_present(), is_loaded(), load(), unload()
    """

    def __init__(
        self,
        model: str,
        host: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        token: Optional[str] = None,
    ) -> None:
        self._model = model
        self.host = host or os.environ.get("OLLAMA_HOST")
        self.username = username or os.environ.get("OLLAMA_USERNAME")
        self.password = password or os.environ.get("OLLAMA_PASSWORD")
        self.token = token or os.environ.get("OLLAMA_TOKEN")

        self._auth = (
            (self.username, self.password) if self.username and self.password else None
        )
        self._cookies = {"token": self.token} if self.token else None
        self._client = Client(self.host, auth=self._auth, cookies=self._cookies)
        self._langfuse = langfuse.get_client()

    # --- Core operations ---
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
            client_kwargs={"auth": self._auth, "cookies": self._cookies},
            reasoning="high" if self._model.startswith("gpt-oss") else None,  # type: ignore
        )

    # --- Model lifecycle / admin ---
    def _list(self) -> List[ModelInfo]:
        response = self._client.list()
        return [ModelInfo.from_ollama_model(model) for model in response["models"]]

    def _pull(self) -> None:
        self._client.pull(self._model)

    def _ps(self) -> List[ModelInfo]:
        response = self._client.ps()
        return [ModelInfo.from_ollama_model(model) for model in response["models"]]

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
