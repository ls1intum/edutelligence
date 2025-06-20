from langchain_core.language_models.chat_models import BaseLanguageModel
from app.grpc import hyperion_pb2_grpc


class ConfigureGradingServicer(hyperion_pb2_grpc.ConfigureGradingServicer):
    """Step 7: Configure Grading Servicer."""

    def __init__(self, model: BaseLanguageModel) -> None:
        """
        Args:
            model: The AI language model to use for grading configuration
        """
        self.model = model
