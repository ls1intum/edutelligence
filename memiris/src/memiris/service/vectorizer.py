from typing_extensions import Sequence

from memiris.service.ollama_service import ollama_client


class Vectorizer:
    """
    A class to handle vectorization of text data for various models.
    """

    vector_models: dict[str, str]

    def __init__(self, vector_models: list[str]) -> None:
        """
        Initialize the Vectorizer with a dictionary of vector models.

        Args:
            vector_models (list[str]): A list of model names to be used for vectorization.
        """
        self.vector_models = {
            f"vector_{i}": vector_models[i] for i in range(len(vector_models))
        }

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
