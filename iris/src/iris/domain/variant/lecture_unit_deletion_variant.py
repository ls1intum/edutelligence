from .abstract_variant import AbstractVariant


class LectureUnitDeletionVariant(AbstractVariant):
    """Variant configuration for the LectureUnitDeletionPipeline."""

    def __init__(
        self,
        variant_id: str,
        name: str,
        description: str,
    ):
        super().__init__(
            variant_id=variant_id,
            name=name,
            description=description,
        )

    def required_models(self) -> set[str]:
        return set()  # No models required for deletion operations
