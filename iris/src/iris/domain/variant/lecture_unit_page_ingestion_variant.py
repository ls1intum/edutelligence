from .abstract_variant import AbstractVariant


class LectureUnitPageIngestionVariant(AbstractVariant):
    """Variant configuration for the LectureUnitPageIngestionPipeline."""

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
        self.chat_model = chat_model
        self.embedding_model = embedding_model

    def required_models(self) -> set[str]:
        return {self.chat_model, self.embedding_model}
