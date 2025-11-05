"""
Abstract interface for language models used in MemIris.
Defines the common methods all concrete LLM adapters must implement.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Sequence, Union

from langchain_core.language_models import BaseChatModel


@dataclass
class ToolFunction:
    name: str
    arguments: Dict[str, Any]


@dataclass
class ToolCall:
    function: ToolFunction


@dataclass
class WrappedChatMessage:
    role: str
    content: Optional[str]
    name: Optional[str] = None
    tool_calls: Optional[Sequence[ToolCall]] = None


@dataclass
class WrappedChatResponse:
    """Normalized chat response across different LLM providers."""

    message: WrappedChatMessage
    model: str
    created_at: Optional[str] = None
    done: Optional[bool] = None
    total_duration: Optional[int] = None
    load_duration: Optional[int] = None
    prompt_eval_count: Optional[int] = None
    prompt_eval_duration: Optional[int] = None
    eval_count: Optional[int] = None
    eval_duration: Optional[int] = None
    raw_response: Any = None

    @classmethod
    def from_ollama_response(cls, response: Any) -> "WrappedChatResponse":
        rd = response.__dict__ if hasattr(response, "__dict__") else response
        msg_dict = rd.get("message", {})
        msg = WrappedChatMessage(
            role=msg_dict.get("role", "assistant"),
            content=msg_dict.get("content"),
            name=msg_dict.get("name"),
            tool_calls=msg_dict.get("tool_calls"),
        )
        return cls(
            message=msg,
            model=rd.get("model", ""),
            created_at=rd.get("created_at"),
            done=rd.get("done"),
            total_duration=rd.get("total_duration"),
            load_duration=rd.get("load_duration"),
            prompt_eval_count=rd.get("prompt_eval_count"),
            prompt_eval_duration=rd.get("prompt_eval_duration"),
            eval_count=rd.get("eval_count"),
            eval_duration=rd.get("eval_duration"),
            raw_response=response,
        )

    @classmethod
    def from_openai_chat(cls, response: Any) -> "WrappedChatResponse":
        # v1 client: response.choices[0].message.content / .tool_calls
        choice = (getattr(response, "choices", None) or [{}])[0]
        message = getattr(choice, "message", None) or {}
        role = getattr(message, "role", "assistant")
        content = getattr(message, "content", None)
        tool_calls = getattr(message, "tool_calls", None)

        # Normalize tool calls to our dataclasses if present
        normalized_tools: Optional[Sequence[ToolCall]] = None
        if tool_calls:
            normalized_tools = []
            for tc in tool_calls:
                fn = getattr(tc, "function", None) or {}
                normalized_tools.append(
                    ToolCall(
                        function=ToolFunction(
                            name=getattr(fn, "name", ""),
                            arguments=getattr(fn, "arguments", {}) or {},
                        )
                    )
                )

        msg = WrappedChatMessage(
            role=role, content=content, tool_calls=normalized_tools
        )
        return cls(
            message=msg, model=getattr(response, "model", ""), raw_response=response
        )


@dataclass
class WrappedEmbeddingResponse:
    """Normalized embedding response across different LLM providers."""

    embeddings: Sequence[Sequence[float]]
    model: str
    raw_response: Any

    @classmethod
    def from_ollama_response(cls, response: Any) -> "WrappedEmbeddingResponse":
        rd = response.__dict__ if hasattr(response, "__dict__") else response
        return cls(
            embeddings=rd.get("embeddings", []),
            model=rd.get("model", ""),
            raw_response=response,
        )

    @classmethod
    def from_openai_embedding(cls, response: Any) -> "WrappedEmbeddingResponse":
        data = getattr(response, "data", [])
        vec = []
        if data:
            emb = getattr(data[0], "embedding", None)
            if emb:
                vec = [emb]
        model = getattr(response, "model", "")
        return cls(embeddings=vec, model=model, raw_response=response)


class AbstractLanguageModel(ABC):
    """
    Abstract base class for a chat/embedding capable language model.
    """

    @property
    @abstractmethod
    def model(self) -> str:
        """The bound model identifier."""
        raise NotImplementedError

    @abstractmethod
    def chat(
        self,
        messages: Sequence[Union[Mapping[str, Any], Any]],
        response_format: Optional[Dict[str, Any]] = None,
        keep_alive: Optional[Union[str, int]] = None,
        options: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> WrappedChatResponse:
        """Send a chat request to the bound model."""
        raise NotImplementedError

    @abstractmethod
    def embed(self, text: str) -> WrappedEmbeddingResponse:
        """Generate embeddings using the bound model."""
        raise NotImplementedError

    @abstractmethod
    def langchain_client(self) -> BaseChatModel:
        """Get a LangChain chat model client for the bound model."""
        raise NotImplementedError

    @abstractmethod
    def ensure_present(self) -> None:
        """Ensure the bound model is available locally (pull if missing)."""
        raise NotImplementedError

    @abstractmethod
    def is_loaded(self) -> bool:
        """Check if the bound model is currently loaded."""
        raise NotImplementedError

    @abstractmethod
    def load(self, duration: str = "5m") -> None:
        """Load the bound model for the given duration."""
        raise NotImplementedError

    @abstractmethod
    def unload(self) -> None:
        """Unload the bound model from memory."""
        raise NotImplementedError
