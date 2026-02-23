from .abstract_variant import AbstractVariant


class LectureIngestionUpdateVariant(AbstractVariant):
    """Variant configuration for the LectureIngestionUpdatePipeline."""

    def __init__(
        self,
        variant_id: str,
        name: str,
        description: str,
        cloud_chat_model: str,
        local_chat_model: str,
        embedding_model: str,
    ):
        super().__init__(
            variant_id=variant_id,
            name=name,
            description=description,
        )
        self.cloud_chat_model = cloud_chat_model
        self.local_chat_model = local_chat_model
        self.embedding_model = embedding_model

    def required_models(self) -> set[str]:
        return {self.cloud_chat_model, self.local_chat_model, self.embedding_model}
