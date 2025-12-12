from .abstract_variant import AbstractVariant


class InconsistencyCheckVariant(AbstractVariant):
    """Variant configuration for the InconsistencyCheckPipeline."""

    def __init__(
        self,
        variant_id: str,
        name: str,
        description: str,
        cloud_solver_model: str,
        local_solver_model: str,
        cloud_prettify_model: str,
        local_prettify_model: str,
    ):
        super().__init__(
            variant_id=variant_id,
            name=name,
            description=description,
        )
        self.cloud_solver_model = cloud_solver_model
        self.local_solver_model = local_solver_model
        self.cloud_prettify_model = cloud_prettify_model
        self.local_prettify_model = local_prettify_model

    def required_models(self) -> set[str]:
        return {
            self.cloud_solver_model,
            self.local_solver_model,
            self.cloud_prettify_model,
            self.local_prettify_model,
        }
