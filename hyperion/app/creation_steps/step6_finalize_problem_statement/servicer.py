from typing import Optional
from langchain_core.language_models.chat_models import BaseLanguageModel
from app.grpc import hyperion_pb2_grpc


class FinalizeProblemStatementServicer(
    hyperion_pb2_grpc.FinalizeProblemStatementServicer
):
    """Step 6: Finalize Problem Statement Servicer."""
    
    def __init__(self, model: BaseLanguageModel) -> None:
        """
        Args:
            model: The AI language model to use for problem statement finalization
        """
        self.model = model
