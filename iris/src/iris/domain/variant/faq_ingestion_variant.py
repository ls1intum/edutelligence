from .abstract_variant import AbstractVariant
from ...cloud_context import isCloudEnabled, localModelString


class FaqIngestionVariant(AbstractVariant):
    """Variant configuration for FAQ ingestion pipeline."""

    def __init__(
        self,
        variant_id: str,
        name: str,
        description: str,
        chat_model: str,
        embedding_model: str,
    ):
        super().__init__(
            variant_id=variant_id,
            name=name,
            description=description,
        )
        self.chat_model = chat_model if isCloudEnabled.get() else localModelString
        self.embedding_model = embedding_model if isCloudEnabled.get() else localModelString

    def required_models(self) -> set[str]:
        return {self.chat_model, self.embedding_model}
