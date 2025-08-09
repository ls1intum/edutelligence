from .abstract_variant import AbstractVariant


class InconsistencyCheckVariant(AbstractVariant):
    """Variant configuration for the InconsistencyCheckPipeline."""

    def __init__(
        self,
        variant_id: str,
        name: str,
        description: str,
        solver_model: str,
    ):
        super().__init__(
            variant_id=variant_id,
            name=name,
            description=description,
        )
        self.solver_model = solver_model

    def required_models(self) -> set[str]:
        return {self.solver_model}
