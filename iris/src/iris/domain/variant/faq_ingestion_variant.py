from .abstract_variant import AbstractVariant


class FaqIngestionVariant(AbstractVariant):
    """Variant configuration for FAQ ingestion pipeline."""

    def __init__(
        self,
        variant_id: str,
        name: str,
        description: str,
        cloud_chat_model: str,
        local_chat_model: str,
        cloud_embedding_model: str,
        local_embedding_model: str,
    ):
        super().__init__(
            variant_id=variant_id,
            name=name,
            description=description,
        )
        self.cloud_chat_model = cloud_chat_model
        self.local_chat_model = local_chat_model
        self.cloud_embedding_model = cloud_embedding_model
        self.local_embedding_model = local_embedding_model

    def required_models(self) -> set[str]:
        return {
            self.cloud_chat_model,
            self.local_chat_model,
            self.cloud_embedding_model,
            self.local_embedding_model,
        }
