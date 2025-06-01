from typing import Optional
from langchain_core.language_models.chat_models import BaseLanguageModel
from app.grpc import hyperion_pb2_grpc


class CreateTestRepositoryServicer(hyperion_pb2_grpc.CreateTestRepositoryServicer):
    """Step 5: Create Test Repository Servicer."""
    
    def __init__(self, model: BaseLanguageModel) -> None:
        """
        Args:
            model: The AI language model to use for test repository creation
        """
        self.model = model
