from langfuse import observe
from typing_extensions import Sequence

from memiris.service.ollama_wrapper import OllamaChatModel


class Vectorizer:
    """
    A class to handle vectorization of text data for various models.
    """

    vector_models: dict[str, OllamaChatModel]

    def __init__(self, vector_models: list[OllamaChatModel]) -> None:
        """
        Initialize the Vectorizer with a dictionary of vector models.

        Args:
            vector_models (list[OllamaChatModel]): A list of bound models to be used for vectorization.
        """
        self.vector_models = {
            f"vector_{i}": vector_models[i] for i in range(len(vector_models))
        }

    @observe(name="vectorization")
    def vectorize(self, query: str) -> dict[str, Sequence[float]]:
        """
        Vectorize the given query using the specified models.
        """
        result: dict[str, Sequence[float]] = {}
        for vector_name, model in self.vector_models.items():
            try:
                embedding_response = model.embed(query)
                result[vector_name] = embedding_response.embeddings[0]
            except Exception as e:
                # Log the error and continue with other models
                print(f"Error generating embedding for {model.model}: {e}")
                result[vector_name] = []
        return result
