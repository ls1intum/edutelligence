from .abstract_variant import AbstractAgentVariant


class TutorSuggestionVariant(AbstractAgentVariant):
    """Variant configuration for the TutorSuggestionPipeline."""

    def __init__(
        self,
        variant_id: str,
        name: str,
        description: str,
        cloud_agent_model: str,
        local_agent_model: str,
        additional_required_models: set[str] | None = None,
    ):
        super().__init__(
            variant_id=variant_id,
            name=name,
            description=description,
            cloud_agent_model=cloud_agent_model,
            local_agent_model=local_agent_model,
        )
        self.additional_required_models = additional_required_models or set()

    def required_models(self) -> set[str]:
        return {self.cloud_agent_model, self.local_agent_model}.union(
            self.additional_required_models
        )
