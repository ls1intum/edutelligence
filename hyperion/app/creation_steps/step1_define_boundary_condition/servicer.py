from langchain_core.language_models.chat_models import BaseLanguageModel
from app.grpc import hyperion_pb2_grpc


class DefineBoundaryConditionServicer(
    hyperion_pb2_grpc.DefineBoundaryConditionServicer
):
    """Step 1: Define Boundary Condition Servicer."""

    def __init__(self, model: BaseLanguageModel) -> None:
        """
        Args:
            model: The AI language model to use for boundary condition processing
        """
        self.model = model
