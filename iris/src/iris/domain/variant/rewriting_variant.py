from .abstract_variant import AbstractVariant


class RewritingVariant(AbstractVariant):
    """Variant configuration for the RewritingPipeline."""

    def __init__(
        self,
        variant_id: str,
        name: str,
        description: str,
        cloud_rewriting_model: str,
        local_rewriting_model: str,
        cloud_consistency_model: str | None = None,
        local_consistency_model: str | None = None,
    ):
        super().__init__(
            variant_id=variant_id,
            name=name,
            description=description,
        )
        self.local_rewriting_model = local_rewriting_model
        self.local_consistency_model = local_consistency_model or local_rewriting_model
        self.cloud_rewriting_model = cloud_rewriting_model
        self.cloud_consistency_model = cloud_consistency_model or cloud_rewriting_model

    def required_models(self) -> set[str]:
        models = {self.cloud_rewriting_model, self.local_rewriting_model}
        if self.cloud_consistency_model != self.cloud_rewriting_model:
            models.add(self.cloud_consistency_model)
        if self.local_consistency_model != self.local_rewriting_model:
            models.add(self.local_consistency_model)
        return models
