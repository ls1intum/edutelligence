from langchain_core.language_models.chat_models import BaseLanguageModel
from app.grpc import hyperion_pb2_grpc


class CreateTemplateRepositoryServicer(
    hyperion_pb2_grpc.CreateTemplateRepositoryServicer
):
    """Step 4: Create Template Repository Servicer."""

    def __init__(self, model: BaseLanguageModel) -> None:
        """
        Args:
            model: The AI language model to use for template repository creation
        """
        self.model = model
