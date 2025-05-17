from typing_extensions import Sequence

from memiris.service.ollama_service import ollama_client


class Vectorizer:
    """
    A class to handle vectorization of text data for various models.
    """

    vector_models: dict[str, str]

    def __init__(self, vector_models: dict[str, str]) -> None:
        """
        Initialize the Vectorizer with a dictionary of vector models.

        Args:
            vector_models (dict[str, str]): A dictionary mapping model names to their respective vectorization methods.
        """
        self.vector_models = vector_models

    def vectorize(self, query: str) -> dict[str, Sequence[float]]:
        """
        Vectorize the given query using the specified models.
        """
        return {
            vector_name: (
                ollama_client.embed(model_name, query).embeddings[0]
                if model_name
                else []
            )
            for vector_name, model_name in self.vector_models.items()
        }
