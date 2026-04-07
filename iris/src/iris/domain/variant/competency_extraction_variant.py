from .abstract_variant import AbstractAgentVariant


class CompetencyExtractionVariant(AbstractAgentVariant):
    """Variant configuration for the CompetencyExtractionPipeline."""

    def __init__(
        self,
        variant_id: str,
        name: str,
        description: str,
        cloud_agent_model: str,
        local_agent_model: str,
    ):
        super().__init__(
            variant_id=variant_id,
            name=name,
            description=description,
            cloud_agent_model=cloud_agent_model,
            local_agent_model=local_agent_model,
        )

    def required_models(self) -> set[str]:
        return {self.cloud_agent_model, self.local_agent_model}
