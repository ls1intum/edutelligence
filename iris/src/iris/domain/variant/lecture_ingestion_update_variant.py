from .abstract_variant import AbstractVariant


class LectureIngestionUpdateVariant(AbstractVariant):
    """Variant configuration for the LectureIngestionUpdatePipeline."""

    def __init__(
        self,
        variant_id: str,
        name: str,
        description: str,
        additional_required_models: set[str] | None = None,
    ):
        super().__init__(
            variant_id=variant_id,
            name=name,
            description=description,
        )
        self.additional_required_models = additional_required_models or set()

    def required_models(self) -> set[str]:
        return set(self.additional_required_models)
