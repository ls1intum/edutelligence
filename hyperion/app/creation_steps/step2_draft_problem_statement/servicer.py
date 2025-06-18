from typing import Optional
from langchain_core.language_models.chat_models import BaseLanguageModel
from app.grpc import hyperion_pb2_grpc


class DraftProblemStatementServicer(hyperion_pb2_grpc.DraftProblemStatementServicer):
    """Step 2: Draft Problem Statement Servicer."""

    def __init__(self, model: BaseLanguageModel) -> None:
        """
        Args:
            model: The AI language model to use for problem statement drafting
        """
        self.model = model
