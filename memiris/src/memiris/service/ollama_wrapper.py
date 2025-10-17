"""
Wrapper around ollama client for better testability and typed returns.
"""

import os
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


class OllamaService:
    """
    Wrapper around the ollama client to provide better testing and typed returns.
    """

    def __init__(
        self,
        host: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        token: Optional[str] = None,
    ) -> None:
        """
        Initialize the OllamaService.

        Args:
            host: The Ollama host URL. Defaults to environment variable OLLAMA_HOST.
            username: The username for authentication. Defaults to environment variable OLLAMA_USERNAME.
            password: The password for authentication. Defaults to environment variable OLLAMA_PASSWORD.
        """
        self.host = host or os.environ.get("OLLAMA_HOST")
        self.username = username or os.environ.get("OLLAMA_USERNAME")
        self.password = password or os.environ.get("OLLAMA_PASSWORD")
        self.token = token or os.environ.get("OLLAMA_TOKEN")

        self.auth_tuple = (
            (self.username, self.password) if self.username and self.password else None
        )
        self.cookies = {"token": self.token} if self.token else None
        self.client = Client(host, auth=self.auth_tuple, cookies=self.cookies)
        self.langfuse_client = langfuse.get_client()

    def langchain_client(self, model: str) -> ChatOllama:
        """
        Get a LangChain ChatOllama client.

        Args:
            model: The model name to use.

        Returns:
            ChatOllama client instance.
        """
        return ChatOllama(
            model=model,
            base_url=self.host,
            client_kwargs={"auth": self.auth_tuple, "cookies": self.cookies},
            reasoning="high" if model.startswith("gpt-oss") else None,  # type: ignore
        )

    def list(self) -> List[ModelInfo]:
        """
        List all available models.

        Returns:
            List of ModelInfo objects representing the available models.
        """
        response = self.client.list()
        return [ModelInfo.from_ollama_model(model) for model in response["models"]]

    def pull(self, model: str) -> None:
        """
        Pull a model from the Ollama registry.

        Args:
            model: The name of the model to pull.
        """
        self.client.pull(model)

    def ps(self) -> List[ModelInfo]:
        """
        List all running models.

        Returns:
            List of ModelInfo objects representing the running models.
        """
        response = self.client.ps()
        return [ModelInfo.from_ollama_model(model) for model in response["models"]]

    def chat(
        self,
        model: str,
        messages: Sequence[Union[Mapping[str, Any], Message]],
        response_format: Optional[Dict[str, Any]] = None,
        keep_alive: Optional[Union[str, int]] = None,
        options: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> WrappedChatResponse:
        """
        Send a chat message to the model.

        Args:
            model: The name of the model to use.
            messages: The list of messages in the conversation.
            response_format: Format to apply to the response, typically a JSON schema.
            keep_alive: Duration to keep the model loaded, e.g., "5m", "1h".
                        Pass 0 to unload the model immediately after the request.
            options: Additional options like temperature, top_p, etc.
            **kwargs: Additional arguments to pass to the ollama client.

        Returns:
            WrappedChatResponse: The response from the model.
        """
        # Create a nested generation
        with self.langfuse_client.start_as_current_generation(
            name="ollama-chat", model=model, input=messages, model_parameters=options
        ) as generation:
            think = "high" if model.startswith("gpt-oss") else None
            response = self.client.chat(
                model,
                messages=messages,
                format=response_format,
                keep_alive=keep_alive,
                options=options,
                think=think,  # type: ignore
                **kwargs,
            )
            generation.update(
                output=response.message,
                metadata=response,
            )
        return WrappedChatResponse.from_ollama_response(response)

    def embed(self, model: str, text: str) -> WrappedEmbeddingResponse:
        """
        Generate embeddings for a text.

        Args:
            model: The name of the embedding model to use.
            text: The text to embed.

        Returns:
            WrappedEmbeddingResponse: The embeddings for the text.
        """
        response = self.client.embed(model, text)
        return WrappedEmbeddingResponse.from_ollama_response(response)

    def ensure_model_present(self, model: str) -> None:
        """
        Ensure that a model is present, pulling it if necessary.

        Args:
            model: The name of the model to ensure is present.
        """
        models = [model_info.name for model_info in self.list()]
        if model not in models:
            print(f"Model {model} not found. Pulling...")
            self.pull(model)
        else:
            print(f"Model {model} is already present.")

    def is_loaded(self, model: str) -> bool:
        """
        Check if a model is currently loaded.

        Args:
            model: The name of the model to check.

        Returns:
            bool: True if the model is loaded, False otherwise.
        """
        models = [model_info.name for model_info in self.ps()]
        return model in models

    def load_model(self, model: str, duration: str = "5m") -> None:
        """
        Load a model into memory.

        Args:
            model: The name of the model to load.
            duration: How long to keep the model loaded, e.g., "5m", "1h".
        """
        print(f"Loading model {model} for {duration}...")
        self.chat(model, messages=[], keep_alive=duration)
        print(f"Model {model} loaded.")

    def unload_model(self, model: str) -> None:
        """
        Unload a model from memory.

        Args:
            model: The name of the model to unload.
        """
        print(f"Unloading model {model}...")
        self.chat(model, messages=[], keep_alive=0)
        print(f"Model {model} unloaded.")
