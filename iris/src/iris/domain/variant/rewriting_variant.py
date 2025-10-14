from .abstract_variant import AbstractVariant
from ...cloud_context import isCloudEnabled, localModelString


class RewritingVariant(AbstractVariant):
    """Variant configuration for the RewritingPipeline."""

    def __init__(
        self,
        variant_id: str,
        name: str,
        description: str,
        rewriting_model: str,
        consistency_model: str = None,
    ):
        super().__init__(
            variant_id=variant_id,
            name=name,
            description=description,
        )
        self.rewriting_model = rewriting_model if isCloudEnabled.get() else localModelString
        self.consistency_model = (consistency_model or rewriting_model) if isCloudEnabled.get() else localModelString

    def required_models(self) -> set[str]:
        models = {self.rewriting_model}
        if self.consistency_model != self.rewriting_model:
            models.add(self.consistency_model)
        return models
