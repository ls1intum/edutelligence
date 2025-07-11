from langfuse import observe
from typing_extensions import Sequence

from memiris.service.ollama_wrapper import OllamaService


class Vectorizer:
    """
    A class to handle vectorization of text data for various models.
    """

    vector_models: dict[str, str]
    ollama_service: OllamaService

    def __init__(self, vector_models: list[str], ollama_service: OllamaService) -> None:
        """
        Initialize the Vectorizer with a dictionary of vector models.

        Args:
            vector_models (list[str]): A list of model names to be used for vectorization.
            ollama_service (OllamaService): The Ollama service to use for embeddings.
        """
        self.vector_models = {
            f"vector_{i}": vector_models[i] for i in range(len(vector_models))
        }
        self.ollama_service = ollama_service

    @observe(name="vectorization")
    def vectorize(self, query: str) -> dict[str, Sequence[float]]:
        """
        Vectorize the given query using the specified models.
        """
        return {
            vector_name: (
                self.ollama_service.embed(model_name, query).embeddings[0]
                if model_name
                else []
            )
            for vector_name, model_name in self.vector_models.items()
        }
